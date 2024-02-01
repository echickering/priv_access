# project/scripts/ec2_deployer.py
import boto3
import yaml
import json
import ipaddress
import logging

class EC2Deployer:
    def __init__(self, config_path='./config/config.yml', aws_credentials_path='./config/aws_credentials.yml'):
        self.config = self.load_config(config_path)
        self.global_tags = self.config['aws'].get('Tags', {})
        self.aws_credentials = self.load_aws_credentials(aws_credentials_path)
        self.state = {}  # Dictionary to keep track of Resource ID in a state file
        self.vm_count = {}  # Dictionary to keep track of VM count per region
        self.ec2_client = None
        self.cf_client = None

    def load_config(self, file_path):
        with open(file_path, 'r') as file:
            return yaml.safe_load(file)

    def load_aws_credentials(self, file_path):
        with open(file_path, 'r') as file:
            return yaml.safe_load(file)['aws_credentials']

    def setup_region_session(self, region):
        # Set up the AWS session with credentials
        boto3.setup_default_session(
            aws_access_key_id=self.aws_credentials['access_key_id'],
            aws_secret_access_key=self.aws_credentials['secret_access_key'],
            region_name=region
        )
        
        self.ec2_client = boto3.client('ec2', region_name=region)
        self.cf_client = boto3.client('cloudformation', region_name=region)

    def get_cf_outputs(self, stack_name):
        try:
            stack_info = self.cf_client.describe_stacks(StackName=stack_name)
            stack_status = stack_info['Stacks'][0]['StackStatus']

            # Check if the stack is in a stable state
            if stack_status in ['CREATE_COMPLETE', 'UPDATE_COMPLETE']:
                # Check if Outputs are present
                if 'Outputs' in stack_info['Stacks'][0]:
                    return {o['OutputKey']: o['OutputValue'] for o in stack_info['Stacks'][0]['Outputs']}
                else:
                    logging.warning(f"No outputs found for stack {stack_name}.")
                    return {}
            else:
                logging.error(f"Stack {stack_name} is not in a stable state: {stack_status}.")
                return {}
        except Exception as e:
            logging.error(f"Error getting outputs for stack {stack_name}: {e}")
            return {}

    def create_security_groups(self, vpc_id, name_prefix):
        # Create tags for security groups
        sg_tags = [{'Key': k, 'Value': v} for k, v in self.global_tags.items()]
        # Create a public security group
        public_group_name = f"{name_prefix}PublicSG"
        sg_public = self.ec2_client.create_security_group(
            GroupName=public_group_name,
            Description="Public Security Group",
            VpcId=vpc_id
        )

        # Add public security group rules
        self.ec2_client.authorize_security_group_ingress(
            GroupId=sg_public['GroupId'],
            IpPermissions=[
                {'IpProtocol': 'tcp', 'FromPort': 443, 'ToPort': 443, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
                {'IpProtocol': '-1', 'FromPort': 0, 'ToPort': 65535, 'IpRanges': [{'CidrIp': '108.44.161.0/24'}]},
                {'IpProtocol': 'udp', 'FromPort': 500, 'ToPort': 500, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
                {'IpProtocol': 'udp', 'FromPort': 4500, 'ToPort': 4500, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
                {'IpProtocol': 'udp', 'FromPort': 4501, 'ToPort': 4501, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]}
            ]
        )

        # Tag the public security group (including the 'Name' tag)
        sg_public_tags = sg_tags.copy()
        sg_public_tags.append({'Key': 'Name', 'Value': public_group_name})
        self.ec2_client.create_tags(
            Resources=[sg_public['GroupId']],
            Tags=sg_public_tags
        )

        # Create a private security group
        private_group_name = f"{name_prefix}PrivateSG"
        sg_private = self.ec2_client.create_security_group(
            GroupName=private_group_name,
            Description="Private Security Group",
            VpcId=vpc_id
        )

        # Add private security group rules (Allowing all RFC1918 traffic)
        for cidr in ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '108.44.161.0/24']:
            self.ec2_client.authorize_security_group_ingress(
                GroupId=sg_private['GroupId'],
                IpPermissions=[
                    {'IpProtocol': '-1', 'FromPort': 0, 'ToPort': 65535, 'IpRanges': [{'CidrIp': cidr}]}
                ]
            )
        # Tag the private security group (including the 'Name' tag)
        sg_private_tags = sg_tags.copy()
        sg_private_tags.append({'Key': 'Name', 'Value': private_group_name})
        self.ec2_client.create_tags(
            Resources=[sg_private['GroupId']],
            Tags=sg_private_tags
        )
        return sg_public['GroupId'], sg_private['GroupId']

    def create_network_interface(self, subnet_id, security_group_id):
        ni_tags = [{'Key': k, 'Value': v} for k, v in self.global_tags.items()]
        network_interface = self.ec2_client.create_network_interface(
            SubnetId=subnet_id,
            Groups=[security_group_id],
            TagSpecifications=[
                {
                    'ResourceType': 'network-interface',
                    'Tags': ni_tags
                }
            ]
        )
        return network_interface['NetworkInterface']['NetworkInterfaceId']

    def create_elastic_ip(self):
        eip = self.ec2_client.allocate_address(Domain='vpc')
        eip_tags = [{'Key': k, 'Value': v} for k, v in self.global_tags.items()]
        self.ec2_client.create_tags(
            Resources=[eip['AllocationId']],
            Tags=eip_tags
        )
        return eip['AllocationId']


    def associate_elastic_ip(self, allocation_id, network_interface_id):
        self.ec2_client.associate_address(
            AllocationId=allocation_id,
            AllowReassociation= False,
            NetworkInterfaceId=network_interface_id
        )

    def deploy_ec2_instance(self, ami_id, instance_type, key_name, user_data, network_interfaces_config, instance_name):
        ec2_tags = [{'Key': k, 'Value': v} for k, v in self.global_tags.items()]
        ec2_tags.append({'Key': 'Name', 'Value': instance_name})  # Append the specific name tag
        # Specify the block device mapping (EBS volumes)
        block_device_mappings = [{
            'DeviceName': '/dev/xvda',  # Adjust this based on AMI default
            'Ebs': {
                'VolumeSize': 60,  # Size in GB
                'VolumeType': 'gp3',
                'Encrypted': True,
                'DeleteOnTermination': True
            },
        }]

        # Specify network interfaces
        network_interfaces = []
        for i, ni_config in enumerate(network_interfaces_config):
            network_interface = {
                'DeviceIndex': i,
                'SubnetId': ni_config['SubnetId'],
                'Groups': [ni_config['SecurityGroupId']],
                'DeleteOnTermination': True
            }
            network_interfaces.append(network_interface)
        # Launch the EC2 instance
        instance = self.ec2_client.run_instances(
            ImageId=ami_id,
            InstanceType=instance_type,
            KeyName=key_name,
            MaxCount=1,
            MinCount=1,
            UserData=user_data,
            BlockDeviceMappings=block_device_mappings,
            NetworkInterfaces=network_interfaces,
            TagSpecifications=[
                {
                    'ResourceType': 'instance',
                    'Tags': ec2_tags
                }
            ],
            MetadataOptions={'HttpTokens': 'required'}
        )
        return instance['Instances'][0]['InstanceId']

    def deploy_region(self, region):
        # Setup AWS clients for the specified region
        self.setup_region_session(region)

        # Get CloudFormation outputs for the region
        region_outputs = self.get_cf_outputs(self.config['aws']['StackName'])
        logging.info(f'Current region_outputs: {region_outputs}')

        # Increment VM count for the region
        self.vm_count[region] = self.vm_count.get(region, 0) + 1

        # Prepare user_data with actual values
        user_data_formatted = self.config['aws']['EC2']['user_data'].format(
            NamePrefix=self.config['aws']['NamePrefix'] + region + f"-VM{self.vm_count[region]}",
            panorama_auth_key=self.config['palo_alto']['panorama']['auth_key'],
            panorama_ip_address1=self.config['palo_alto']['panorama']['ip_address1'],
            panorama_ip_address2=self.config['palo_alto']['panorama']['ip_address2'],
            PanoramaTemplate=self.config['palo_alto']['panorama']['PanoramaTemplate'],
            PanoramaDeviceGroup=self.config['palo_alto']['panorama']['PanoramaDeviceGroup']
        )
        user_data_semi_colon_separated = user_data_formatted.replace('\n', ';').rstrip(';')
        logging.info(f'User-Data sent to EC2: {user_data_semi_colon_separated}')

        # Create Security Groups
        sg_public_id, sg_private_id = self.create_security_groups(region_outputs['VpcId'], self.config['aws']['NamePrefix'])

        # Define network interfaces configuration
        network_interfaces_config = [
            {'SubnetId': region_outputs['Subnet1Id'], 'SecurityGroupId': sg_public_id},
            {'SubnetId': region_outputs['Subnet2Id'], 'SecurityGroupId': sg_private_id},
            {'SubnetId': region_outputs['Subnet2Id'], 'SecurityGroupId': sg_private_id}
        ]

        # EC2 Settings
        ami_id = self.config['aws']['Regions'][region]['ngfw_ami_id']
        instance_type = self.config['aws']['EC2']['instance_type']
        key_name = self.config['aws']['Regions'][region]['key_name']
        
        # Define VM name
        vm_name = f"{self.config['aws']['NamePrefix']}{region}-VM{self.vm_count[region]}"

        # Deploy EC2 instance
        instance_id = self.deploy_ec2_instance(
            ami_id,
            instance_type,
            key_name,
            user_data_semi_colon_separated,
            network_interfaces_config,
            vm_name
        )

        # Wait for instance to be in running state (optional)
        self.ec2_client.get_waiter('instance_running').wait(InstanceIds=[instance_id])

        # Retrieve network interfaces and sort them by device index
        instance_info = self.ec2_client.describe_instances(InstanceIds=[instance_id])
        network_interfaces = instance_info['Reservations'][0]['Instances'][0]['NetworkInterfaces']
        sorted_network_interfaces = sorted(network_interfaces, key=lambda ni: ni['Attachment']['DeviceIndex'])

        # Record the created resources in the state dictionary
        self.record_state(region, instance_id, vm_name, sg_public_id, sg_private_id, sorted_network_interfaces)

    def record_state(self, region, instance_id, vm_name, sg_public_id, sg_private_id, sorted_network_interfaces):
        # This method updates the state dictionary with the new resources created
        self.state[region] = self.state.get(region, {})
        self.state[region][instance_id] = {
            'vm_name': vm_name,
            'SecurityGroups': {'Public': sg_public_id, 'Private': sg_private_id},
            'NetworkInterfaces': [],
            'ElasticIPs': []
        }
        # Create and associate Elastic IPs to the first two network interfaces (with indexes 0 and 1)
        for ni in sorted_network_interfaces[:2]:
            ni_id = ni['NetworkInterfaceId']
            eip_alloc_id = self.create_elastic_ip()
            self.associate_elastic_ip(eip_alloc_id, ni_id)
            
            # Get public IP for the EIP
            eip_info = self.ec2_client.describe_addresses(AllocationIds=[eip_alloc_id])
            public_ip = eip_info['Addresses'][0]['PublicIp']

            self.state[region][instance_id]['ElasticIPs'].append({
                'AllocationId': eip_alloc_id,
                'InterfaceId': ni_id,
                'PublicIP': public_ip
            })
        # Create additional state file information
        for ni in sorted_network_interfaces:
            subnet_info = self.ec2_client.describe_subnets(SubnetIds=[ni['SubnetId']])
            subnet_cidr = subnet_info['Subnets'][0]['CidrBlock']
            # Calculate Default Gateway (second IP in the subnet)
            subnet_network = ipaddress.ip_network(subnet_cidr)
            default_gw = str(next(subnet_network.hosts()))
            # Calculate PrivateIpCidr
            private_ip_cidr = f"{ni['PrivateIpAddress']}/{subnet_network.prefixlen}"
            self.state[region][instance_id]['NetworkInterfaces'].append({
                'InterfaceId': ni['NetworkInterfaceId'],
                'DeviceIndex': ni['Attachment']['DeviceIndex'],
                'PrivateIpAddress': ni['PrivateIpAddress'],
                'DefaultGW': default_gw,
                'PrivateIpCidr': private_ip_cidr
            })
        
        logging.info(f"EC2 Instance created in {region}: {instance_id}")
        # Write the state information to a file
        with open('./state/state-ec2.json', 'w') as f:
            json.dump(self.state, f, indent=4)        

    def main(self):
        # Deploy resources for each region in the configuration
        for region in self.config['aws']['Regions'].keys():
            self.deploy_region(region)

        # Write the state information to a file
        with open('./state/state-ec2.json', 'w') as f:
            json.dump(self.state, f, indent=4)

if __name__ == '__main__':
    EC2Deployer().main()