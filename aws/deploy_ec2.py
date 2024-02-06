# project/aws/deploy_ec22.py
import boto3
import yaml
import logging
import base64
import os

class EC2Deployer:
    def __init__(self, config_path='./config/config.yml', aws_credentials_path='./config/aws_credentials.yml', output_dir='./config'):
        self.config = self.load_config(config_path)
        self.aws_credentials = self.load_aws_credentials(aws_credentials_path)
        self.output_dir = output_dir
        self.cf_client = None

    def load_config(self, file_path):
        with open(file_path, 'r') as file:
            return yaml.safe_load(file)

    def load_aws_credentials(self, file_path):
        with open(file_path, 'r') as file:
            return yaml.safe_load(file)['aws_credentials']

    # This function now takes an additional parameter for the region
    def load_template_for_region(self, region):
        template_path = os.path.join(self.output_dir, f"{region}_ec2_template.yml")
        with open(template_path, 'r') as file:
            return file.read()

    def setup_client(self, region):
        session = boto3.Session(
            aws_access_key_id=self.aws_credentials['access_key_id'],
            aws_secret_access_key=self.aws_credentials['secret_access_key'],
            region_name=region
        )
        self.cf_client = session.client('cloudformation')

    def prepare_user_data(self, region):
        # Retrieve the base user_data template from the configuration
        user_data_template = self.config['aws']['EC2']['user_data']
        
        # Dynamic values to replace in the user_data template
        replacements = {
            '{NamePrefix}': self.config['aws']['NamePrefix'] + region,
            '{panorama_auth_key}': self.config['palo_alto']['panorama']['auth_key'],
            '{panorama_ip_address1}': self.config['palo_alto']['panorama']['ip_address1'],
            '{panorama_ip_address2}': self.config['palo_alto']['panorama']['ip_address2'],
            '{PanoramaTemplateStack}': self.config['palo_alto']['panorama']['PanoramaTemplateStack'],
            '{PanoramaDeviceGroup}': self.config['palo_alto']['panorama']['PanoramaDeviceGroup'],
        }

        # Replace placeholders in the user_data template with actual values
        for placeholder, value in replacements.items():
            user_data_template = user_data_template.replace(placeholder, value)

        # Convert newline characters to semi-colons, remove trailing semi-colons
        user_data_semi_colon_separated = user_data_template.replace('\n', ';').rstrip(';')

        # Encode the modified user_data in Base64
        user_data_encoded = base64.b64encode(user_data_semi_colon_separated.encode('utf-8')).decode('utf-8')

        return user_data_encoded

    def get_vpc_stack_outputs(self, region):
        """Fetch outputs from the VPC CloudFormation stack."""
        stack_name = self.config['aws']['StackName']  # The name of your VPC stack
        self.setup_client(region)
        
        try:
            response = self.cf_client.describe_stacks(StackName=stack_name)
            outputs = response['Stacks'][0]['Outputs']
            return {output['OutputKey']: output['OutputValue'] for output in outputs}
        except Exception as e:
            logging.error(f"Error fetching VPC stack outputs: {e}")
            return {}

    def deploy_stack(self, region):
        self.setup_client(region)
        region_config = self.config['aws']['Regions'][region]
        stack_name = self.config['aws']['StackNameEC2']
        template_body = self.load_template_for_region(region)  # Load the region-specific template

        user_data_encoded = self.prepare_user_data(region)

        # Fetch subnet IDs and VPC ID from VPC stack outputs
        vpc_stack_outputs = self.get_vpc_stack_outputs(region)
        subnet1_id = vpc_stack_outputs.get('Subnet1Id', '')
        subnet2_id = vpc_stack_outputs.get('Subnet2Id', '')
        vpc_id = vpc_stack_outputs.get('VpcId', '')  # Fetch VPC ID

        parameters = [
            {'ParameterKey': 'AMIId', 'ParameterValue': region_config['ngfw_ami_id']},
            {'ParameterKey': 'InstanceType', 'ParameterValue': self.config['aws']['EC2']['instance_type']},
            {'ParameterKey': 'KeyName', 'ParameterValue': region_config['key_name']},
            {'ParameterKey': 'EC2UserData', 'ParameterValue': user_data_encoded},
            {'ParameterKey': 'Subnet1Id', 'ParameterValue': subnet1_id},
            {'ParameterKey': 'Subnet2Id', 'ParameterValue': subnet2_id},
            {'ParameterKey': 'MyVpcId', 'ParameterValue': vpc_id},  # Include VPC ID parameter
            {'ParameterKey': 'InstanceName', 'ParameterValue': f"{self.config['aws']['NamePrefix']}{region}-VM"}
        ]

        try:
            # Try to update the stack first
            logging.info(f"Attempting to update stack {stack_name} in {region}...")
            response = self.cf_client.update_stack(
                StackName=stack_name,
                TemplateBody=template_body,
                Parameters=parameters,
                Capabilities=['CAPABILITY_NAMED_IAM']
            )
            action = "Update Initiated"
            logging.info(f"Stack {stack_name} update initiated in {region}.")
        except self.cf_client.exceptions.ClientError as error:
            if "does not exist" in str(error):
                # If the stack does not exist, create it
                logging.info(f"Stack {stack_name} does not exist in {region}, creating...")
                response = self.cf_client.create_stack(
                    StackName=stack_name,
                    TemplateBody=template_body,
                    Parameters=parameters,
                    Capabilities=['CAPABILITY_NAMED_IAM'],
                    OnFailure='ROLLBACK'
                )
                action = "Creation Initiated"
            elif "No updates are to be performed." in str(error):
                logging.info(f"No updates are to be performed for stack {stack_name} in {region}.")
                return {"Status": "No Update Needed"}
            else:
                raise error

        # Wait for stack creation or update to complete
        if action == "Creation Initiated":
            waiter = self.cf_client.get_waiter('stack_create_complete')
        else:
            waiter = self.cf_client.get_waiter('stack_update_complete')

        logging.info(f"Waiting for stack {stack_name} to reach a stable state in {region}...")
        waiter.wait(StackName=stack_name)

        logging.info(f"Stack {stack_name} {action.lower()} successfully in {region}.")
        return {"Status": action, "StackId": response['StackId']}

    def deploy(self):
        # Loop through each region defined in the config and deploy the stack for that region
        for region in self.config['aws']['Regions']:
            logging.info(f"Deploying EC2 stack in {region}...")
            self.deploy_stack(region)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    ec2_deployer = EC2Deployer(config_path='./config/config.yml', aws_credentials_path='./config/aws_credentials.yml', template_path='./config/ec2_template.yml')
    ec2_deployer.deploy()