import yaml
import os
import copy

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
    def __init__(self, config_path, base_template_path, output_dir='./config'):
        self.config = self.load_yaml_file(config_path)
        self.base_template = self.load_yaml_file(base_template_path)
        self.output_dir = output_dir

    def load_yaml_file(self, file_path):
        with open(file_path, 'r') as file:
            return yaml.load(file, Loader=yaml.SafeLoader)

    def write_yaml_file(self, data, file_path):
        with open(file_path, 'w') as file:
            yaml.dump(data, file, Dumper=yaml.SafeDumper, sort_keys=False)

    def duplicate_for_az(self, az_count):
        updated_template = copy.deepcopy(self.base_template)

        # Duplicate Parameters, Resources, and Outputs for each AZ
        for item in ['Parameters', 'Resources', 'Outputs']:
            entries_to_duplicate = {k: v for k, v in updated_template.get(item, {}).items() if k.endswith('1')}
            for i in range(2, az_count + 1):
                for key, value in entries_to_duplicate.items():
                    new_key = key[:-1] + str(i)
                    updated_template[item][new_key] = copy.deepcopy(value)  # Correctly use copy.deepcopy here
                    if item == 'Resources':
                        # Update references within duplicated resources
                        for prop_key, prop_val in value.get('Properties', {}).items():
                            if isinstance(prop_val, dict) and 'Ref' in prop_val and prop_val['Ref'].endswith('1'):
                                updated_template[item][new_key]['Properties'][prop_key]['Ref'] = prop_val['Ref'][:-1] + str(i)
                    elif item == 'Outputs':
                        # Update references within duplicated outputs
                        if 'Value' in value and 'Ref' in value['Value'] and value['Value']['Ref'].endswith('1'):
                            updated_template[item][new_key]['Value']['Ref'] = value['Value']['Ref'][:-1] + str(i)

        return updated_template

    def update_templates(self):
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        for region, details in self.config['aws']['Regions'].items():
            az_count = len(details['availability_zones'])
            region_template = self.duplicate_for_az(az_count)
            region_template['Description'] += f" for {region}"
            region_output_path = os.path.join(self.output_dir, f"{region}_vpc_template.yml")
            self.write_yaml_file(region_template, region_output_path)

if __name__ == "__main__":
    config_path = 'config/config.yml'
    base_template_path = 'config/vpc_template.yml'
    updater = UpdateVpcTemplate(config_path, base_template_path)
    updater.update_templates()
    print("Updated templates are saved.")
