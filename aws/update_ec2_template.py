import logging
import yaml
import copy
import os
import re

def setup_yaml():
    yaml.SafeLoader.add_constructor('!Ref', lambda loader, node: {'Ref': loader.construct_scalar(node)})
    yaml.SafeLoader.add_constructor('!GetAtt', lambda loader, node: {'Fn::GetAtt': loader.construct_scalar(node).split('.')})
    yaml.SafeLoader.add_constructor('!Sub', lambda loader, node: {'Fn::Sub': loader.construct_scalar(node)})

    def represent_dict_order(dumper, data):
        return dumper.represent_mapping('tag:yaml.org,2002:map', data.items())
    
    yaml.add_representer(dict, represent_dict_order, Dumper=yaml.SafeDumper)

setup_yaml()

class UpdateEc2Template:
    def __init__(self, config, base_template, output_dir='./config'):
        self.config = config
        self.base_template = base_template
        self.output_dir = output_dir

    def write_yaml_file(self, data, file_path):
        with open(file_path, 'w') as file:
            yaml.dump(data, file, Dumper=yaml.SafeDumper, sort_keys=False)

    def duplicate_for_az(self, az_names, region):
        updated_template = copy.deepcopy(self.base_template)  # Deep copy to preserve the original template
        for az_name in az_names:
            # az_suffix = az_name.split(region)[-1].replace('-', '')
            min_ec2_count = self.config['aws']['Regions'][region]['availability_zones'][az_name].get('min_ec2_count', 1)
            logging.debug(f'EC2 count: {min_ec2_count} for AZ: {az_name}')
            # Loop through the EC2 count for each AZ
            for count in range(1, min_ec2_count + 1):
                az_suffix = az_name.split(region)[-1].replace('-', '')
                logging.debug(f'az_suffix: {az_suffix}')
                count_suffix = f"{count}{az_suffix}"  # New suffix format
                logging.debug(f'full suffix: {count_suffix}')
                # Duplicate and update references for each EC2 instance within the AZ
                self.duplicate_and_update_references(updated_template, count_suffix, az_name, region)
        # Delete entries ending with "1" after all updates are done
        self.delete_entries_ending_with_1(updated_template)
        return updated_template

    def duplicate_and_update_references(self, template, az_suffix, az_name, region):
        for section in ['Parameters', 'Resources', 'Outputs']:
            items = template.get(section, {})
            for key, value in list(items.items()):  # Use list to duplicate items during iteration
                if key.endswith('1'):
                    new_key = key.replace('1', az_suffix)
                    # Ensure that only items relevant to the current AZ are updated
                    if az_name in key or not any(az in key for az in self.config['aws']['Regions'][region]['availability_zones']):
                        template[section][new_key] = self.update_references(copy.deepcopy(value), az_suffix)
                    # Optionally, consider deleting the original '1' entries here if they should not be retained

    def update_references(self, item, az_suffix):
        if isinstance(item, dict):
            for key, value in item.items():
                if key in ['Ref', 'Fn::GetAtt']:
                    item[key] = self.update_reference(value, az_suffix, is_get_att=(key == 'Fn::GetAtt'))
                elif key == 'Fn::Sub':
                    item[key] = self.update_fn_sub(value, az_suffix)
                elif key == 'DependsOn':
                    # Handle updating DependsOn references
                    if isinstance(value, list):
                        item[key] = [self.update_reference(v, az_suffix) for v in value]
                    else:
                        item[key] = self.update_reference(value, az_suffix)
                else:
                    item[key] = self.update_references(value, az_suffix)
        elif isinstance(item, list):
            return [self.update_references(i, az_suffix) for i in item]
        return item

    def update_reference(self, ref, az_suffix, is_get_att=False):
        if isinstance(ref, str):
            if '1' in ref:
                return ref.replace('1', az_suffix)
            # Additional handling for references that may not directly include '1' but are affected
            return ref if not ref.endswith('1') else ref.replace('1', az_suffix)
        elif is_get_att and isinstance(ref, list):
            # Specifically handling 'Fn::GetAtt' list to ensure resource names are updated
            updated_ref = [self.update_reference(part, az_suffix) for part in ref]
            return updated_ref
        return ref

    def update_fn_sub(self, sub, az_suffix):
        if isinstance(sub, str):
            return self.perform_substitution(sub, az_suffix)
        elif isinstance(sub, list):
            updated_sub = [self.perform_substitution(sub[0], az_suffix)]
            if len(sub) > 1:
                updated_sub.append({k: self.update_reference(v, az_suffix) for k, v in sub[1].items()})
            return updated_sub
        return sub

    def perform_substitution(self, string, az_suffix):
        # Use a function as the replacement argument to re.sub
        def replacement(match):
            # Extract the matched group, append az_suffix, and format correctly
            return '${' + match.group(1) + az_suffix + '}'
        
        # Perform the substitution using the replacement function
        return re.sub(r'\$\{([^}]+)1\}', replacement, string)

    def delete_entries_ending_with_1(self, template):
        for section in ['Parameters', 'Resources', 'Outputs']:
            section_items = template.get(section, {})
            if isinstance(section_items, dict):  # Ensure we are working with a dictionary
                keys_to_delete = [key for key in section_items if key.endswith('1')]
                for key in keys_to_delete:
                    del section_items[key]

    def update_templates(self):
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        for region, details in self.config['aws']['Regions'].items():
            logging.info(f'Processing EC2 Template for {region}')
            az_names = list(details['availability_zones'].keys())
            region_template = self.duplicate_for_az(az_names, region)
            region_output_path = os.path.join(self.output_dir, f"{region}_ec2_template.yml")
            self.write_yaml_file(region_template, region_output_path)