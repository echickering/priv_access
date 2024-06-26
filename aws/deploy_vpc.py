# project/aws/deploy_vpc2.py
import boto3
import logging
import threading

class VPCDeployer:
    def __init__(self, config, aws_credentials):
        self.config = config
        self.aws_credentials = aws_credentials
        self.name_prefix = self.config['aws']['NamePrefix']

    def deploy_stack_thread(self, region, region_config):
        """Thread target for deploying a stack."""
        try:
            cf_client = self.setup_client(region)
            logging.info(f"Starting deployment in {region}...")
            self.main(cf_client, region, region_config)
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

    def deploy_stack(self, cf_client, region, template_body, parameters, stack_name):
        try:
            logging.info(f"Updating stack {stack_name} in {region}...")
            response = cf_client.update_stack(
                StackName=stack_name,
                TemplateBody=template_body,
                Parameters=parameters,
                Capabilities=['CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM']
            )
            action = "Update Initiated"
        except cf_client.exceptions.ClientError as error:
            if error.response['Error']['Message'] == 'No updates are to be performed.':
                logging.debug("No VPC updates are needed to be performed.")
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

    def main(self, cf_client, region, config):
    # for region, region_config in self.config['aws']['Regions'].items():
        logging.info(f"Deploying VPC in region: {region}")

        if self.name_prefix is not None:
            vpc_name = self.name_prefix + region.replace('-', '')
        else:
            logging.error("name_prefix is None. Ensure it is correctly initialized.")
            return

        with open(f'config/{region}_vpc_template.yml', 'r') as file:
            template_body = file.read()

        base_cf_parameters = [
            {'ParameterKey': 'NamePrefix', 'ParameterValue': self.config['aws']['NamePrefix']},
            {'ParameterKey': 'VpcName', 'ParameterValue': vpc_name},
            {'ParameterKey': 'VpcCidr', 'ParameterValue': config['vpc_cidr']}
        ]
        az_parameters = []
        count = 0
        for az, az_config in config['availability_zones'].items():
            # Conditionally add Second availability zone and its dependents
            count += 1
            logging.debug(f'Current AZ: {az}')
            az_key = az.split(region)[-1].replace('-','')
            logging.debug(f'AZ Name Key: {az_key}')
            if 'az_name' in az_config:
                az_parameters.append({'ParameterKey': f'AvailabilityZone{az_key}', 'ParameterValue': az_config['az_name']})
            if 'untrust_subnet_cidr' in az_config:
                az_parameters.append({'ParameterKey': f'UnTrustCidrAZ{az_key}', 'ParameterValue': az_config['untrust_subnet_cidr']})
            if 'trust_subnet_cidr' in az_config:
                az_parameters.append({'ParameterKey': f'TrustCidrAZ{az_key}', 'ParameterValue': az_config['trust_subnet_cidr']})

            # Conditionally add TgwId and TgwCidr if they exist in the config
            if 'tgw_id' in az_config:
                az_parameters.append({'ParameterKey': 'TgwId', 'ParameterValue': az_config['tgw_id']})
            if 'tgw_cidr' in az_config:
                az_parameters.append({'ParameterKey': 'TgwCidr', 'ParameterValue': az_config['tgw_cidr']})
                            
        full_parameters = base_cf_parameters + az_parameters

        logging.debug(f'Full CF Parameters: {full_parameters}')
        result = self.deploy_stack(cf_client, region, template_body, full_parameters, stack_name=self.config['aws']['StackNameVPC'])

        if result:
            if result['Status'] in ["Update Initiated", "Creation Initiated"]:
                logging.info(f"Stack deployment completed in {region}: {result['StackId']}")
            elif result['Status'] == "No Update Needed":
                logging.info(f"No update was needed for the stack in {region}.")
        else:
            logging.info(f"An unexpected error occurred in {region}")

    def deploy(self):
        logging.debug(f"Debug of load_config: config={self.config}, name_prefix={self.name_prefix}")
        threads = []
        for region, region_config in self.config['aws']['Regions'].items():
            # Pass region and region_config as keyword arguments
            thread = threading.Thread(target=self.deploy_stack_thread, args=(region, region_config))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        logging.info("Completed deploying VPCs in all regions.")