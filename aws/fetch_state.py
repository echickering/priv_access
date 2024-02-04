import boto3
import yaml
import ipaddress
import logging

class FetchState:
    def __init__(self, config_path='./config/config.yml', aws_credentials_path='./config/aws_credentials.yml'):
        self.config = self.load_yaml_file(config_path)
        self.aws_credentials = self.load_yaml_file(aws_credentials_path)['aws_credentials']
        self.cf_clients = {}

    def load_yaml_file(self, file_path):
        with open(file_path, 'r') as file:
            return yaml.safe_load(file)

    def setup_client(self, region):
        if region not in self.cf_clients:
            session = boto3.Session(
                aws_access_key_id=self.aws_credentials['access_key_id'],
                aws_secret_access_key=self.aws_credentials['secret_access_key'],
                region_name=region
            )
            self.cf_clients[region] = session.client('cloudformation')
        return self.cf_clients[region]

    def fetch_stack_outputs(self, region, stack_name):
        cf_client = self.setup_client(region)
        try:
            stack_info = cf_client.describe_stacks(StackName=stack_name)
            outputs = stack_info['Stacks'][0]['Outputs']
            outputs_dict = {output['OutputKey']: output['OutputValue'] for output in outputs}
            
            # Debug logging to show fetched outputs
            logging.info(f"Fetched stack outputs for {stack_name} in {region}: {outputs_dict}")
            
            return outputs_dict
        except Exception as e:
            logging.error(f"Error fetching outputs for stack {stack_name} in region {region}: {e}")
            return {}

    def get_first_usable_ip(self, cidr):
        network = ipaddress.ip_network(cidr)
        first_usable_ip = next(network.hosts())
        return str(first_usable_ip)

    def process_vpc_subnet_data(self, region):
        vpc_stack_name = self.config['aws']['StackName']
        vpc_outputs = self.fetch_stack_outputs(region, vpc_stack_name)

        untrust_nexthop = self.get_first_usable_ip(vpc_outputs['Subnet1Cidr'])
        trust_nexthop = self.get_first_usable_ip(vpc_outputs['Subnet2Cidr'])
        return untrust_nexthop, trust_nexthop

    def process_ec2_interface_data(self, region):
        ec2_stack_name = self.config['aws']['StackNameEC2']
        ec2_outputs = self.fetch_stack_outputs(region, ec2_stack_name)

        processed_data = {}
        # Assuming instance numbers are sequential and start from 1
        for instance_num in range(1, 10):  # Adjust the range as needed based on possible max instances
            public_untrust_ip = ec2_outputs.get(f'PublicEIP{instance_num}')
            untrust_ip = self.fetch_eni_private_ip(region, ec2_outputs.get(f'PublicInterface{instance_num}'))
            mgmt_ip = self.fetch_eni_private_ip(region, ec2_outputs.get(f'MgmtInterface{instance_num}'))
            trust_ip = self.fetch_eni_private_ip(region, ec2_outputs.get(f'PrivateInterface{instance_num}'))

            if not all([public_untrust_ip, untrust_ip, mgmt_ip, trust_ip]):
                logging.debug(f"Partial or no data fetched for EC2 instance {instance_num} in region {region}. Skipping.")
                continue  # Skip to the next instance if critical data is missing

            processed_data[f'instance{instance_num}'] = {
                'public_untrust_ip': public_untrust_ip,
                'untrust_ip': untrust_ip,
                'trust_ip': trust_ip,
                'mgmt_ip': mgmt_ip
            }

        if not processed_data:
            logging.error(f"No valid EC2 instance data found in region {region}.")
            return {}  # Return an empty dict if no valid data was found for any instance

        return processed_data

    def fetch_eni_private_ip(self, region, eni_id):
        if eni_id is None:
            logging.debug(f"ENI ID is None for region {region}. Skipping fetch for private IP.")
            return None
        ec2_client = boto3.client('ec2', region_name=region, aws_access_key_id=self.aws_credentials['access_key_id'], aws_secret_access_key=self.aws_credentials['secret_access_key'])
        try:
            eni_info = ec2_client.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
            private_ip = eni_info['NetworkInterfaces'][0]['PrivateIpAddress']
            return private_ip
        except Exception as e:
            logging.error(f"Error fetching private IP for ENI {eni_id} in region {region}: {e}")
            return None

    def fetch_and_process_state(self):
        state = {}
        for region in self.config['aws']['Regions']:
            untrust_nexthop, trust_nexthop = self.process_vpc_subnet_data(region)
            instance_data = self.process_ec2_interface_data(region)  # This now returns a dictionary

            # Process each instance's data from the dictionary
            for instance_num, data in instance_data.items():
                public_untrust_ip = data.get('public_untrust_ip')
                untrust_ip = data.get('untrust_ip')
                trust_ip = data.get('trust_ip')
                mgmt_ip = data.get('mgmt_ip')

                state[f'{region}_instance_{instance_num}'] = {
                    'untrust_nexthop': untrust_nexthop,
                    'trust_nexthop': trust_nexthop,
                    'public_untrust_ip': public_untrust_ip,
                    'untrust_ip': untrust_ip,
                    'trust_ip': trust_ip,
                    'mgmt_ip': mgmt_ip,
                }
        logging.info(f'Current State: {state}')
        return state