import boto3
import yaml
import logging
import threading

class VPCDeployer:
    def __init__(self, config, aws_credentials):
        self.config = config
        self.aws_credentials = aws_credentials
        self.name_prefix = None  # Initialize name_prefix to None

    def load_config(self, file_path):
        with open(file_path, 'r') as file:
            return yaml.safe_load(file)

    def deploy_stack(self, cf_client, template_body, parameters, stack_name):
        try:
            logging.info(f"Updating stack {stack_name}...")
            response = cf_client.update_stack(
                StackName=stack_name,
                TemplateBody=template_body,
                Parameters=parameters,
                Capabilities=['CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM']
            )
            action = "Update Initiated"
        except cf_client.exceptions.ClientError as error:
            if error.response['Error']['Message'] == 'No updates are to be performed.':
                logging.info("No updates are to be performed.")
                return {"Status": "No Update Needed"}
            elif 'does not exist' in error.response['Error']['Message']:
                logging.info(f"Creating stack {stack_name}...")
                response = cf_client.create_stack(
                    StackName=stack_name,
                    TemplateBody=template_body,
                    Parameters=parameters,
                    Capabilities=['CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM'],
                    OnFailure='ROLLBACK'
                )
                action = "Creation Initiated"
            else:
                raise

        # Determine the appropriate waiter
        if action == "Creation Initiated":
            waiter = cf_client.get_waiter('stack_create_complete')
        else:
            waiter = cf_client.get_waiter('stack_update_complete')

        logging.info(f"Waiting for stack {stack_name} to reach a stable state...")
        waiter.wait(StackName=stack_name)

        return {"Status": action, "StackId": response['StackId']}

    def load_config_and_deploy(self, config_file_path, aws_credentials_file_path):
        self.config = self.load_config(config_file_path)  # Set the config attribute
        aws_creds = self.load_config(aws_credentials_file_path)
        self.aws_credentials = aws_creds['aws_credentials']
        self.name_prefix = self.config['aws']['NamePrefix']  # Initialize name_prefix here

        logging.info(f"Debug: config={self.config}, name_prefix={self.name_prefix}")

        # Call the main method directly instead of creating a new instance
        self.main()

    def main(self):
        for region, region_config in self.config['aws']['Regions'].items():
            logging.info(f"Deploying in region: {region}")

            # Check if name_prefix is None before using it
            if self.name_prefix is not None:
                vpc_name = self.name_prefix + region.replace('-', '')
            else:
                logging.error("name_prefix is None. Ensure it is correctly initialized.")
                return

            boto3.setup_default_session(
                aws_access_key_id=self.aws_credentials['access_key_id'],
                aws_secret_access_key=self.aws_credentials['secret_access_key'],
                region_name=region
            )

            with open('config/vpc_template.yml', 'r') as file:
                template_body = file.read()

            cf_client = boto3.client('cloudformation')
            cf_parameters = [
                {
                    'ParameterKey': 'NamePrefix',
                    'ParameterValue': self.config['aws']['NamePrefix']
                },
                {
                    'ParameterKey': 'VpcName',
                    'ParameterValue': vpc_name
                },
                {
                    'ParameterKey': 'VpcCidr',
                    'ParameterValue': region_config['vpc_cidr']
                },
                {
                    'ParameterKey': 'Subnet1Cidr',
                    'ParameterValue': region_config['subnet1_cidr_block']
                },
                {
                    'ParameterKey': 'Subnet2Cidr',
                    'ParameterValue': region_config['subnet2_cidr_block']
                }
            ]

            result = self.deploy_stack(cf_client, template_body, cf_parameters, stack_name=self.config['aws']['StackName'])

            if result:
                if result['Status'] in ["Update Initiated", "Creation Initiated"]:
                    logging.info(f"Stack deployment initiated in {region}: {result['StackId']}")
                elif result['Status'] == "No Update Needed":
                    logging.info(f"No update was needed for the stack in {region}.")
            else:
                logging.info(f"An unexpected error occurred in {region}")

if __name__ == '__main__':
    # Create an instance of VPCDeployer and run load_config_and_deploy
    deployer_instance = VPCDeployer(None, None)  # Pass None as placeholders for config and credentials
    deployer_instance.load_config_and_deploy('./config/config.yml', './config/aws_credentials.yml')
