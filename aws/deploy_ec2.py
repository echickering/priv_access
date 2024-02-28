# project/aws/deploy_ec22.py
import boto3
import logging
import base64
import os
import threading

class EC2Deployer:
    def __init__(self, config, aws_credentials, output_dir='./config'):
        self.config = config
        self.aws_credentials = aws_credentials
        self.name_prefix = self.config['aws']['NamePrefix']
        self.output_dir = output_dir

    def deploy_stack_thread(self, region):
        """Thread target for deploying a stack."""
        try:
            cf_client = self.setup_client(region)
            logging.info(f"Starting deployment in {region}...")
            self.deploy_or_update_stack(cf_client, region)
            logging.info(f"Finished deployment in {region}.")
        except Exception as e:
            logging.error(f"Failed to deploy in {region}: {e}")

    def setup_client(self, region):
        """Setup and return a new CloudFormation client for the given region."""
        session = boto3.Session(
            aws_access_key_id=self.aws_credentials['access_key_id'],
            aws_secret_access_key=self.aws_credentials['secret_access_key'],
            region_name=region
        )
        return session.client('cloudformation')

    def load_template_for_region(self, region_az_config):
        template_path = os.path.join(self.output_dir, f"{region_az_config}_ec2_template.yml")
        with open(template_path, 'r') as file:
            return file.read()

    def prepare_user_data(self, az):
        """Retrieve the base user_data template from the configuration"""
        user_data_template = self.config['aws']['EC2']['user_data']
        
        # Dynamic values to replace in the user_data template
        replacements = {
            '{NamePrefix}': self.name_prefix + az,
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

    def get_vpc_stack_outputs(self, cf_client):
        """Fetch outputs from the VPC CloudFormation stack."""
        stack_name = self.config['aws']['StackNameVPC']
        try:
            response = cf_client.describe_stacks(StackName=stack_name)
            outputs = response['Stacks'][0]['Outputs']
            return {output['OutputKey']: output['OutputValue'] for output in outputs}
        except Exception as e:
            logging.error(f"Error fetching VPC stack outputs: {e}")
            return {}

    def deploy_or_update_stack(self, cf_client, region):
        """
        Attempt to update or create a CloudFormation stack, then wait for it to reach a stable state.
        Exits the process with a critical error if a recreated stack fails to stabilize.
        """
        stack_name = f"{self.config['aws']['StackNameEC2']}"  # Define stack name
        template_body = self.load_template_for_region(region)  # Use region name to fetch the correct template
        vpc_stack_outputs = self.get_vpc_stack_outputs(cf_client)  # Fetch VPC stack outputs for the region
        parameters = self.construct_parameters_for_region(region, vpc_stack_outputs)

        logging.debug(f'Region:{region} Parameters: {parameters}')

        action, recreation_attempted = self.attempt_stack_creation_or_update(region, cf_client, stack_name, template_body, parameters)

        # Wait for stack to reach a stable state
        if not self.wait_for_stack_stable(cf_client, stack_name):
            if recreation_attempted:
                logging.critical(f'Stack {stack_name} failed to stabilize after recreation in {region}. Exiting process.')
                logging.critical(f'OS Exit was called. So far this is due to unsupported instance type in region {region}')
                """We are using OS Exit here.. most likely due to local zone not supporting the instance type"""
                os._exit(1)
            else:
                logging.error(f"Stack {stack_name} did not reach a stable state in the allotted time in {region}.")
                return {"Status": "Failed"}
        else:
            logging.info(f"Stack {stack_name} successfully {action.lower()} in {region}.")
            return {"Status": action}

    def attempt_stack_creation_or_update(self, region, cf_client, stack_name, template_body, parameters):
        """
        Attempt to create or update a CloudFormation stack and handle ROLLBACK_COMPLETE state.
        Returns the action taken and a flag indicating whether a recreation was attempted.
        """
        try:
            logging.info(f"Attempting to update stack {stack_name} in {region}...")
            cf_client.update_stack(
                StackName=stack_name,
                TemplateBody=template_body,
                Parameters=parameters,
                Capabilities=['CAPABILITY_NAMED_IAM']
            )
            return "Update Initiated", False
        except cf_client.exceptions.ClientError as error:
            error_message = str(error.response['Error']['Message'])
            if "does not exist" in error_message:
                logging.info(f"Creating stack {stack_name} in {region}...")
                cf_client.create_stack(
                    StackName=stack_name,
                    TemplateBody=template_body,
                    Parameters=parameters,
                    Capabilities=['CAPABILITY_NAMED_IAM']
                )
                return "Creation Initiated", False
            elif "ROLLBACK_COMPLETE" in error_message:
                logging.info(f"Stack {stack_name} is in ROLLBACK_COMPLETE state in {region}. Deleting and recreating...")
                cf_client.delete_stack(StackName=stack_name)
                self.wait_for_stack_delete_complete(cf_client, stack_name, region)
                cf_client.create_stack(
                    StackName=stack_name,
                    TemplateBody=template_body,
                    Parameters=parameters,
                    Capabilities=['CAPABILITY_NAMED_IAM']
                )
                return "Recreation Initiated", True
            elif "No updates are to be performed." in error_message:
                logging.info(f"No updates are to be performed for stack {stack_name} in {region}.")
                return "No Update Needed", False
            else:
                raise error

    def wait_for_stack_delete_complete(self, cf_client, stack_name, region):
        """
        Wait for a CloudFormation stack to be completely deleted.
        """
        try:
            deletion_waiter = cf_client.get_waiter('stack_delete_complete')
            logging.info(f"Waiting for stack {stack_name} deletion to complete...")
            deletion_waiter.wait(StackName=stack_name)
            logging.info(f"Stack {stack_name} in region {region} deleted successfully.")
        except Exception as e:
            logging.error(f"Error waiting for stack {stack_name} deletion: {e}")

    def wait_for_stack_stable(self, cf_client, stack_name):
        """
        Wait for a CloudFormation stack to reach a stable state using waiters.
        """
        try:
            # Create a waiter for stack creation completion
            creation_waiter = cf_client.get_waiter('stack_create_complete')
            # Create a waiter for stack update completion
            update_waiter = cf_client.get_waiter('stack_update_complete')

            # Fetch the current stack status to determine which waiter to use
            response = cf_client.describe_stacks(StackName=stack_name)
            stack_status = response['Stacks'][0]['StackStatus']

            # Depending on the current stack status, wait for the appropriate state
            if stack_status == 'CREATE_IN_PROGRESS':
                logging.info(f"Waiting for stack {stack_name} creation to complete...")
                creation_waiter.wait(StackName=stack_name)
            elif stack_status in ['UPDATE_IN_PROGRESS', 'UPDATE_COMPLETE_CLEANUP_IN_PROGRESS']:
                logging.info(f"Waiting for stack {stack_name} update to complete...")
                update_waiter.wait(StackName=stack_name)

            # After waiting, fetch the stack status again to ensure it's stable
            response = cf_client.describe_stacks(StackName=stack_name)
            final_status = response['Stacks'][0]['StackStatus']
            if final_status in ['CREATE_COMPLETE', 'UPDATE_COMPLETE']:
                logging.info(f"Stack {stack_name} reached a stable state: {final_status}.")
                return True
            else:
                logging.error(f"Stack {stack_name} reached an unexpected state: {final_status}.")
                return False
        except Exception as e:
            logging.error(f"Error waiting for stack {stack_name} to stabilize: {e}")
            return False

    def construct_parameters_for_region(self, region, vpc_stack_outputs):
        region_config = self.config['aws']['Regions'][region]
        user_data_encoded = self.prepare_user_data(region)  # Encode user data for the entire region

        parameters = [
            {'ParameterKey': 'EC2UserData', 'ParameterValue': user_data_encoded},
            {'ParameterKey': 'MyVpcId', 'ParameterValue': vpc_stack_outputs.get('VpcId', '')},
            {'ParameterKey': 'KeyName', 'ParameterValue': region_config['key_name']},
            {'ParameterKey': 'AMIId', 'ParameterValue': region_config['ngfw_ami_id']},
        ]
        # Iterate through each AZ
        for az, az_config in region_config['availability_zones'].items():
            ec2_counter = 1  # Counts total EC2 instances across all AZs          
            min_ec2_count = az_config.get('min_ec2_count', 1)
            # Iterate through each instance in the AZ
            for _ in range(min_ec2_count):
                logging.debug(f'Region: {region}')
                logging.debug(f'AZ: {az}')
                az_suffix = az.split(region)[-1].replace('-', '')
                logging.debug(f'AZ Suffix: {az_suffix} for AZ: {az}')
                logging.debug(f'EC2 Count: {ec2_counter} for AZ: {az}')
                ec2_count_name = f'{ec2_counter}{az_suffix}'
                logging.debug(f'Full EC2 Count and Suffix: {ec2_count_name}')
                logging.debug(f"InstanceName:{self.name_prefix}{ec2_count_name}")
                parameters += [
                    {'ParameterKey': f'UnTrustID{ec2_count_name}', 'ParameterValue': vpc_stack_outputs.get(f'UnTrustIDAZ{az_suffix}', '')},
                    {'ParameterKey': f'TrustID{ec2_count_name}', 'ParameterValue': vpc_stack_outputs.get(f'TrustIDAZ{az_suffix}', '')},
                    {'ParameterKey': f'InstanceName{ec2_count_name}', 'ParameterValue': f"{self.name_prefix}{az_suffix}-VM{ec2_counter}"},
                    {'ParameterKey': f'NetworkBorderGroupValue{ec2_count_name}', 'ParameterValue': az_config['NetworkBorderGroup']},
                    {'ParameterKey': f'InstanceType{ec2_count_name}', 'ParameterValue': az_config['instance_type']}
                ]
                ec2_counter += 1  # Increment for the next EC2 instance
        logging.debug(f'Parameters: {parameters}')
        return parameters

    def deploy(self):
        """Deploy stacks across all configured regions using threading."""
        threads = []
        for region in self.config['aws']['Regions']:
            thread = threading.Thread(target=self.deploy_stack_thread, args=(region,))
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join()
        logging.info("All deployments completed.")