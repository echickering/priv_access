import boto3
import yaml
import ipaddress
import logging

class FetchState:
    def __init__(self, config, aws_credentials):
        self.config = config
        self.aws_credentials = aws_credentials
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
            logging.debug(f"Fetched stack outputs for {stack_name} in {region}: {outputs_dict}")
            return outputs_dict
        except Exception as e:
            logging.error(f"Error fetching outputs for stack {stack_name} in region {region}: {e}")
            return {}

    def get_first_usable_ip_and_netmask(self, cidr):
        network = ipaddress.ip_network(cidr)
        first_usable_ip = next(network.hosts())
        netmask = network.prefixlen
        return str(first_usable_ip), str(netmask)

    def process_vpc_subnet_data(self, region):
        vpc_stack_name = self.config['aws']['StackNameVPC']
        vpc_outputs = self.fetch_stack_outputs(region, vpc_stack_name)
        subnet_data = {}
        az_counter = 1  # Counter based on the number of AZs in the region

        for az in self.config['aws']['Regions'][region]['availability_zones']:
            # Fetch the subnet CIDR outputs from the VPC stack
            az_suffix = az.split(region)[-1].replace('-', '')
            untrust_cidr_key = f'UnTrustCidrAZ{az_suffix}'
            trust_cidr_key = f'TrustCidrAZ{az_suffix}'

            # Get the first usable IP and netmask for each subnet CIDR
            untrust_nexthop, untrust_netmask = self.get_first_usable_ip_and_netmask(vpc_outputs.get(untrust_cidr_key, ''))
            trust_nexthop, trust_netmask = self.get_first_usable_ip_and_netmask(vpc_outputs.get(trust_cidr_key, ''))

            subnet_data[az] = {
                'untrust_nexthop': untrust_nexthop,
                'trust_nexthop': trust_nexthop,
                'untrust_netmask': untrust_netmask,  # Include the CIDR netmask
                'trust_netmask': trust_netmask       # Include the CIDR netmask
            }
            az_counter += 1  # Increment for each AZ processed

        return subnet_data

    def fetch_eni_private_ip(self, region, eni_id):
        if eni_id is None:
            logging.debug(f"ENI ID is None for region {region}. Skipping fetch for private IP.")
            return None, None  # Return None for both primary and secondary IPs
        ec2_client = boto3.client('ec2', region_name=region, aws_access_key_id=self.aws_credentials['access_key_id'], aws_secret_access_key=self.aws_credentials['secret_access_key'])
        try:
            eni_info = ec2_client.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
            logging.debug(f'Interface details: {eni_info}')
            private_ip = eni_info['NetworkInterfaces'][0]['PrivateIpAddress']
            # Correctly handle secondary IPs
            secondary_ips = [ip['PrivateIpAddress'] for ip in eni_info['NetworkInterfaces'][0]['PrivateIpAddresses'] if not ip['Primary']]
            secondary_ip = f"{secondary_ips[0]}/32" if secondary_ips else None  # Correctly fetch the first secondary IP
            logging.debug(f'Secondary IP from fetch_eni_private_ip: {secondary_ip}')
            return private_ip, secondary_ip
        except Exception as e:
            logging.error(f"Error fetching private IP for ENI {eni_id} in region {region}: {e}")
            return None, None

    def fetch_and_process_state(self):
        state = {}

        for region in self.config['aws']['Regions']:
            # Fetch VPC subnet data to get next-hop information and netmasks
            vpc_subnet_data = self.process_vpc_subnet_data(region)

            # ec2_counter = 1  # Reset counter for each region
            ec2_stack_name = f"{self.config['aws']['StackNameEC2']}"
            ec2_outputs = self.fetch_stack_outputs(region, ec2_stack_name)

            for az, az_data in vpc_subnet_data.items():
                untrust_nexthop = az_data['untrust_nexthop']
                trust_nexthop = az_data['trust_nexthop']
                untrust_netmask = az_data['untrust_netmask']
                trust_netmask = az_data['trust_netmask']
                az_suffix = az.split(region)[-1].replace('-', '')

                for instance_num in range(1, self.config['aws']['Regions'][region]['availability_zones'][az]['min_ec2_count'] + 1):
                    ec2_count_name = f'{instance_num}{az_suffix}'
                    public_untrust_ip = ec2_outputs.get(f'PublicEIP{ec2_count_name}')
                    logging.info(f'instance: {ec2_count_name} public_untrust: {public_untrust_ip}')
                    untrust_ip_base, _ = self.fetch_eni_private_ip(region, ec2_outputs.get(f'PublicInterface{ec2_count_name}'))
                    mgmt_ip, _ = self.fetch_eni_private_ip(region, ec2_outputs.get(f'MgmtInterface{ec2_count_name}'))
                    trust_ip_base, secondary_ip = self.fetch_eni_private_ip(region, ec2_outputs.get(f'PrivateInterface{ec2_count_name}'))

                    untrust_ip = f"{untrust_ip_base}/{untrust_netmask}" if untrust_ip_base else None
                    untrust_ip_single = f"{untrust_ip_base}" if untrust_ip_base else None
                    trust_ip = f"{trust_ip_base}/{trust_netmask}" if trust_ip_base else None
                    trust_ip_single = f"{trust_ip_base}" if trust_ip_base else None

                    gp_pool_key = f'user_pool{instance_num}'
                    ebgp_as_key = f'ebgp_as{instance_num}'
                    gp_pool = self.config['aws']['Regions'][region]['availability_zones'][az]['globalprotect'].get(gp_pool_key, 'N/A')
                    ebgp_as = self.config['aws']['Regions'][region]['availability_zones'][az]['globalprotect'].get(ebgp_as_key, 'N/A')

                    # Use a more descriptive key to ensure uniqueness
                    state_key = f'{az}_instance_{instance_num}'
                    state[state_key] = {
                        'public_untrust_ip': public_untrust_ip,
                        'untrust_ip': untrust_ip,
                        'untrust_ip_base': untrust_ip_single,
                        'untrust_router_id': untrust_ip_single,
                        'untrust_nexthop': untrust_nexthop,
                        'trust_ip': trust_ip,
                        'trust_ip_base': trust_ip_single,
                        'trust_secondary_ip': secondary_ip,
                        'trust_nexthop': trust_nexthop,
                        'mgmt_ip': mgmt_ip,
                        'vpn_user_pool': gp_pool,
                        'eBGP_AS': ebgp_as
                    }

        return state