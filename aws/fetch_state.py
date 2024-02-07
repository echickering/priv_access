# project/aws/fetch_state2.py
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
            logging.debug(f"Fetched stack outputs for {stack_name} in {region}: {outputs_dict}")
            
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

    def extract_cidr_suffix(self, cidr):
        """Extract and return the CIDR suffix from a CIDR string."""
        try:
            _, suffix = cidr.split('/')
            return suffix
        except ValueError:
            logging.error(f"Invalid CIDR format: {cidr}")
            return None

    def process_ec2_interface_data(self, region):
        ec2_stack_name = self.config['aws']['StackNameEC2']
        ec2_outputs = self.fetch_stack_outputs(region, ec2_stack_name)

        # Fetch Subnet CIDRs for appending
        vpc_stack_name = self.config['aws']['StackName']
        vpc_outputs = self.fetch_stack_outputs(region, vpc_stack_name)
        subnet1_cidr = vpc_outputs.get('Subnet1Cidr', '')
        subnet2_cidr = vpc_outputs.get('Subnet2Cidr', '')

        # Extract the CIDR suffix from Subnet CIDRs
        untrust_subnet_mask = self.extract_cidr_suffix(subnet1_cidr)
        trust_subnet_mask = self.extract_cidr_suffix(subnet2_cidr)

        # Determine max EC2 count from config.yml
        max_ec2 = self.config['aws']['Regions'][region]['max_ec2_count']+1

        processed_data = {}
        
        # Assuming instance numbers are sequential and start from 1
        for instance_num in range(1, max_ec2):  # Adjust based on possible max instances
            public_untrust_ip = ec2_outputs.get(f'PublicEIP{instance_num}')
            untrust_ip_base, _ = self.fetch_eni_private_ip(region, ec2_outputs.get(f'PublicInterface{instance_num}'))
            untrust_ip = f"{untrust_ip_base}/{untrust_subnet_mask}" if untrust_ip_base and trust_subnet_mask else None
            mgmt_ip, _ = self.fetch_eni_private_ip(region, ec2_outputs.get(f'MgmtInterface{instance_num}'))
            trust_ip_base, trust_secondary_ip = self.fetch_eni_private_ip(region, ec2_outputs.get(f'PrivateInterface{instance_num}'))
            trust_ip = f"{trust_ip_base}/{trust_subnet_mask}" if trust_ip_base and trust_subnet_mask else None
            logging.debug(f'Secondary IP returned to process_ec2_interfaces_data: {trust_secondary_ip}')
            gp_pool = self.config['aws']['Regions'][region]['globalprotect'][f'user_pool{instance_num}']
            on_prem_vpn_settings = self.config['vpn']['on_prem_vpn_settings']
            logging.info(f'Fetch State Current GP Pool: {gp_pool}')
            untrust_nexthop, trust_nexthop = self.process_vpc_subnet_data(region)

            # Correctly append the secondary IP to the state data
            if not all([public_untrust_ip, untrust_ip, trust_ip, mgmt_ip]):
                logging.debug(f"Partial or no data fetched for EC2 instance {instance_num} in region {region}. Skipping.")
                continue

            processed_data[f'instance{instance_num}'] = {
                'public_untrust_ip': public_untrust_ip,
                'untrust_ip': untrust_ip,  # Includes CIDR
                'untrust_ip_base': untrust_ip_base,  # IP No CIDR
                'untrust_router_id': untrust_ip_base, #RouterID for Untrust VR
                'untrust_nexthop': untrust_nexthop,
                'trust_nexthop': trust_nexthop,
                'trust_ip': trust_ip,      # Includes CIDR
                'trust_ip_base': trust_ip_base, #Ip without CIDR
                'trust_secondary_ip': trust_secondary_ip,  # Secondary trust IP
                'mgmt_ip': mgmt_ip,
                'gp_pool': gp_pool
            }
            # Dynamically adding on-prem VPN settings to the processed_data
            for site, ip in on_prem_vpn_settings.items():
                processed_data[f'instance{instance_num}'][site] = ip
        logging.info(f'Current state: {processed_data}')
        if not processed_data:
            logging.error(f"No valid EC2 instance data found in region {region}.")
            return {}  # Return an empty dict if no valid data was found for any instance

        logging.debug(f'State Data from class FetchState: {processed_data}')
        return processed_data

    def fetch_eni_private_ip(self, region, eni_id):
        if eni_id is None:
            logging.debug(f"ENI ID is None for region {region}. Skipping fetch for private IP.")
            return None, None  # Return None for both primary and secondary IPs
        ec2_client = boto3.client('ec2', region_name=region, aws_access_key_id=self.aws_credentials['access_key_id'], aws_secret_access_key=self.aws_credentials['secret_access_key'])
        try:
            eni_info = ec2_client.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
            logging.debug(f'Interface details: {eni_info}')
            private_ip = eni_info['NetworkInterfaces'][0]['PrivateIpAddress']
            secondary_ips = eni_info['NetworkInterfaces'][0].get('PrivateIpAddresses', [])[1:2]  # Get the first secondary IP if exists
            secondary_ip = f"{secondary_ips[0]['PrivateIpAddress']}/32" if secondary_ips else None
            logging.debug(f'Secondary IP from fetch_eni_private_ip: {secondary_ip}')
            return private_ip, secondary_ip
        except Exception as e:
            logging.error(f"Error fetching private IP for ENI {eni_id} in region {region}: {e}")
            return None, None

    def fetch_and_process_state(self):
        state = {}
        for region in self.config['aws']['Regions']:
            # your existing logic to process each region and instance
            instance_data = self.process_ec2_interface_data(region)
            for instance_num, data in instance_data.items():
                # Build the state with data already including dynamic keys
                state[f'{region}_instance_{instance_num}'] = data
        return state