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

    def replace_refs_in_text(self, file_path):
        """
        Parse the template file as text and replace 'Ref:', 'Fn::GetAtt:', and 'Fn::Sub:' 
        with '!Ref', '!GetAtt', and '!Sub' respectively.
        """
        with open(file_path, 'r') as file:
            content = file.read()
        
        # Replace 'Ref:' with '!Ref'
        updated_content = content.replace('Ref:', '!Ref')

        # Replace 'Fn::GetAtt:' with '!GetAtt'
        updated_content = updated_content.replace('Fn::GetAtt:', '!GetAtt')

        # Replace 'Fn::Sub:' with '!Sub'
        updated_content = updated_content.replace('Fn::Sub:', '!Sub')

        # Write the updated content back to the file
        with open(file_path, 'w') as file:
            file.write(updated_content)

    def update_templates(self):
        for region, settings in self.config['aws']['Regions'].items():
            min_count = settings.get('min_ec2_count', 1)  # Default to 1 if not specified
            max_count = settings.get('max_ec2_count', 1)  # Default to 1 if not specified

            # Adjust min_ec2_count if it exceeds max_ec2_count
            if min_count > max_count:
                logging.warning(f"min_ec2_count ({min_count}) is greater than max_ec2_count ({max_count}) for region {region}. Setting min_ec2_count to max_ec2_count.")
                min_count = max_count  # Set min_ec2_count to max_ec2_count

            # Continue with template update
            template = self.load_yaml_file(self.base_template_path)
            self.prepare_template_for_count(template, min_count)

            # Write the updated template to the regional template file
            regional_template_path = os.path.join(self.output_dir, f"{region}_ec2_template.yml")
            self.write_yaml_file(template, regional_template_path)

            # Apply text replacements for 'Ref:', 'Fn::GetAtt:', and 'Fn::Sub:'
            self.replace_refs_in_text(regional_template_path)
            logging.info(f"Template updated for {region}: {regional_template_path}")

    def prepare_template_for_count(self, template, min_count):
        for count in range(2, min_count + 1):
            self.duplicate_resources(template, count)

    def duplicate_resources(self, template, count):
        # Duplicate resources
        new_resources = {}
        for resource_name, resource_content in template['Resources'].items():
            if resource_name.endswith('1'):
                new_resource_name = resource_name[:-1] + str(count)
                new_resource_content = copy.deepcopy(resource_content)
                self.update_references(new_resource_content, '1', str(count))
                new_resources[new_resource_name] = new_resource_content
        template['Resources'].update(new_resources)

        # Duplicate outputs
        new_outputs = {}
        for output_name, output_content in template.get('Outputs', {}).items():
            if output_name.endswith('1'):
                new_output_name = output_name[:-1] + str(count)
                new_output_content = copy.deepcopy(output_content)
                self.update_references(new_output_content, '1', str(count))
                new_outputs[new_output_name] = new_output_content
        template['Outputs'].update(new_outputs)


    def update_references(self, resource_content, old_suffix, new_suffix):
        if isinstance(resource_content, dict):
            for key, value in resource_content.items():
                if key == '!GetAtt' and isinstance(value, list):
                    # Update the resource name in the list if it ends with the old suffix
                    updated_list = [v.replace(old_suffix, new_suffix) if v.endswith(old_suffix) else v for v in value]
                    resource_content[key] = updated_list
                elif isinstance(value, str) and value.endswith(old_suffix):
                    resource_content[key] = value.replace(old_suffix, new_suffix)
                elif isinstance(value, (list, dict)):
                    self.update_references(value, old_suffix, new_suffix)
        elif isinstance(resource_content, list):
            for i, item in enumerate(resource_content):
                if isinstance(item, str) and item.endswith(old_suffix):
                    resource_content[i] = item.replace(old_suffix, new_suffix)
                else:
                    self.update_references(item, old_suffix, new_suffix)

if __name__ == '__main__':
    config_path = os.path.join(os.path.dirname(__file__), 'config', 'config.yml')
    base_template_path = os.path.join(os.path.dirname(__file__), 'config', 'ec2_template.yml')
    output_dir = os.path.join(os.path.dirname(__file__), 'config')
    updater = UpdateEc2Template(config_path, base_template_path, output_dir)
    updater.update_templates()