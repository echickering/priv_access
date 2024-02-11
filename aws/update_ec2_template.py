# project/aws/update_ec2_template2.py
import yaml
import copy
import os
import logging
import boto3

# Define custom constructors for CloudFormation-specific tags
def setup_yaml():
    yaml.SafeLoader.add_constructor('!Ref', lambda loader, node: {'Ref': loader.construct_scalar(node)})
    yaml.SafeLoader.add_constructor('!GetAtt', lambda loader, node: {'Fn::GetAtt': loader.construct_scalar(node).split('.')})
    yaml.SafeLoader.add_constructor('!Sub', lambda loader, node: {'Fn::Sub': loader.construct_scalar(node)})

    def represent_dict_order(dumper, data):
        return dumper.represent_mapping('tag:yaml.org,2002:map', data.items())

    yaml.add_representer(dict, represent_dict_order, Dumper=yaml.SafeDumper)

setup_yaml()

class UpdateEc2Template:
    def __init__(self, config_path, base_template_path, output_dir='./config'):
        self.config = self.load_yaml_file(config_path)
        self.base_template_path = base_template_path
        self.output_dir = output_dir

    def load_yaml_file(self, file_path):
        with open(file_path, 'r') as file:
            return yaml.load(file, Loader=yaml.SafeLoader)

    def write_yaml_file(self, data, file_path):
        with open(file_path, 'w') as file:
            yaml.dump(data, file, Dumper=yaml.SafeDumper, sort_keys=False)

    def update_templates(self):
        for region, region_config in self.config['aws']['Regions'].items():
            logging.info(f"Processing Region: {region}")
            original_template = self.load_yaml_file(self.base_template_path)

            global_resource_count = 1  # Initialize with 1 for the first set of resources

            for az, az_config in region_config['availability_zones'].items():
                logging.info(f"Processing AZ: {az} in Region: {region}")
                min_count = az_config.get('min_ec2_count', 1)

                for count in range(1, min_count + 1):
                    self.duplicate_resources(original_template, global_resource_count, duplicate_all=True)
                    global_resource_count += 1  # Increment for the next set of resources

            # Write the updated template to the regional template file, once all AZs are processed
            regional_template_path = os.path.join(self.output_dir, f"{region}_ec2_template.yml")
            self.write_yaml_file(original_template, regional_template_path)
            logging.info(f"Combined Template updated for Region {region}: {regional_template_path}")

    def duplicate_resources(self, template, count, duplicate_all=True):
        def update_name_and_refs(content, old_suffix, new_suffix):
            if isinstance(content, str) and old_suffix in content:
                return content.replace(old_suffix, new_suffix)
            elif isinstance(content, dict):
                return {k: update_name_and_refs(v, old_suffix, new_suffix) for k, v in content.items()}
            elif isinstance(content, list):
                return [update_name_and_refs(item, old_suffix, new_suffix) for item in content]
            return content

        # Always duplicate all sections for each instance
        for section in ['Parameters', 'Resources', 'Outputs']:
            new_items = {}
            for name, item in template.get(section, {}).items():
                if name.endswith('1'):  # Identifies items intended for duplication
                    new_name = name[:-1] + str(count)  # Adjust the name for duplication
                    new_item = copy.deepcopy(item)
                    new_items[new_name] = update_name_and_refs(new_item, '1', str(count))
            template[section].update(new_items)

if __name__ == '__main__':
    config_path = os.path.join(os.path.dirname(__file__), 'config', 'config.yml')
    base_template_path = os.path.join(os.path.dirname(__file__), 'config', 'ec2_template.yml')
    output_dir = os.path.join(os.path.dirname(__file__), 'config')
    updater = UpdateEc2Template(config_path, base_template_path, output_dir)
    updater.update_templates()