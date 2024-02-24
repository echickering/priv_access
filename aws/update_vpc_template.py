import yaml
import os
import copy
import logging

def setup_yaml():
    yaml.SafeLoader.add_constructor('!Ref', lambda loader, node: {'Ref': loader.construct_scalar(node)})
    yaml.SafeLoader.add_constructor('!GetAtt', lambda loader, node: {'Fn::GetAtt': loader.construct_scalar(node).split('.')})
    yaml.SafeLoader.add_constructor('!Sub', lambda loader, node: {'Fn::Sub': loader.construct_scalar(node)})
    
    def construct_and(loader, node):
        value = loader.construct_sequence(node)
        return {'Fn::And': value}
    
    def construct_not(loader, node):
        value = loader.construct_sequence(node)
        return {'Fn::Not': value}
    
    def construct_equals(loader, node):
        value = loader.construct_sequence(node)
        return {'Fn::Equals': value}
    
    yaml.SafeLoader.add_constructor('!And', construct_and)
    yaml.SafeLoader.add_constructor('!Not', construct_not)
    yaml.SafeLoader.add_constructor('!Equals', construct_equals)

    def represent_dict_order(dumper, data):
        return dumper.represent_mapping('tag:yaml.org,2002:map', data.items())

    yaml.add_representer(dict, represent_dict_order, Dumper=yaml.SafeDumper)

setup_yaml()


class UpdateVpcTemplate:
    def __init__(self, config, base_template, output_dir='./config'):
        self.config = config
        self.base_template = base_template
        self.output_dir = output_dir

    def write_yaml_file(self, data, file_path):
        with open(file_path, 'w') as file:
            yaml.dump(data, file, Dumper=yaml.SafeDumper, sort_keys=False)

    def duplicate_for_az(self, az_names, region):
        updated_template = copy.deepcopy(self.base_template)
        for az_name in az_names:
            az_suffix = az_name.split(region)[-1].replace('-', '')  # Removing '-' for consistency
            for item in ['Parameters', 'Resources', 'Outputs']:
                entries_to_duplicate = {k: v for k, v in updated_template.get(item, {}).items() if '1' in k}
                for key, value in entries_to_duplicate.items():
                    new_key = key.replace('1', az_suffix)  # Renaming keys
                    updated_template[item][new_key] = copy.deepcopy(value)
        self.delete_entries_ending_with_1(updated_template)
        self.update_resource_and_output_references(updated_template, az_names, region)
        return updated_template

    def delete_entries_ending_with_1(self, template):
        for section in ['Parameters', 'Resources', 'Outputs']:
            keys_to_delete = [key for key in template.get(section, {}).keys() if key.endswith('1')]
            for key in keys_to_delete:
                del template[section][key]

    def update_resource_and_output_references(self, template, az_names, region):
        for item_type in ['Resources', 'Outputs']:
            for item_key, item_value in template.get(item_type, {}).items():
                if 'Properties' in item_value:
                    self.update_references_in_properties(item_value['Properties'], item_key, az_names, region)
                if item_type == 'Outputs' and 'Value' in item_value:
                    self.update_reference_in_value(item_value['Value'], item_key, az_names, region)

    def update_references_in_properties(self, properties, item_key, az_names, region):
        for az_name in az_names:
            az_suffix = az_name.split(region)[-1].replace('-', '')
            # Only update references for items that belong to the current az_suffix
            if item_key.endswith(az_suffix):
                for prop_key, prop_value in properties.items():
                    if isinstance(prop_value, dict):
                        self.update_dict_references(prop_value, '1', az_suffix)

    def update_reference_in_value(self, value, item_key, az_names, region):
        for az_name in az_names:
            az_suffix = az_name.split(region)[-1].replace('-', '')
            # Only update references for items that belong to the current az_suffix
            if item_key.endswith(az_suffix) and isinstance(value, dict):
                self.update_dict_references(value, '1', az_suffix)

    def update_dict_references(self, dictionary, old_suffix, new_suffix):
        for key in ['Ref', 'Fn::GetAtt']:
            if key in dictionary:
                if isinstance(dictionary[key], list):
                    # Assuming the first element in list is the reference to update
                    dictionary[key][0] = self.update_reference(dictionary[key][0], old_suffix, new_suffix)
                else:
                    dictionary[key] = self.update_reference(dictionary[key], old_suffix, new_suffix)

    def update_reference(self, reference, old_suffix, new_suffix):
        # Update the reference if it ends with the old_suffix
        if reference.endswith(old_suffix):
            return reference[:-len(old_suffix)] + new_suffix
        return reference
    
    def update_templates(self):
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        for region, details in self.config['aws']['Regions'].items():
            az_names = [az for az in details['availability_zones']]
            region_template = self.duplicate_for_az(az_names, region)
            region_template['Description'] += f" for {region}"
            region_output_path = os.path.join(self.output_dir, f"{region}_vpc_template.yml")
            self.write_yaml_file(region_template, region_output_path)