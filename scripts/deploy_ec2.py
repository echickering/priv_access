import boto3
import yaml
import json
import ipaddress
import logging

# Function to load configuration from YAML file
def load_config(file_path):
    with open(file_path, 'r') as file:
        return yaml.safe_load(file)

# Function to retrieve CloudFormation stack outputs
def get_cf_outputs(cf_client, stack_name):
    stack_info = cf_client.describe_stacks(StackName=stack_name)
    outputs = stack_info['Stacks'][0]['Outputs']
    return {o['OutputKey']: o['OutputValue'] for o in outputs}

# Function to create security groups
def create_security_groups(ec2_client, vpc_id, name_prefix):
    # Create a public security group
    sg_public = ec2_client.create_security_group(
        GroupName=f"{name_prefix}PublicSG",
        Description="Public Security Group",
        VpcId=vpc_id
    )

    # Add public security group rules
    ec2_client.authorize_security_group_ingress(
        GroupId=sg_public['GroupId'],
        IpPermissions=[
            {'IpProtocol': 'tcp', 'FromPort': 443, 'ToPort': 443, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
            {'IpProtocol': '-1', 'FromPort': 0, 'ToPort': 65535, 'IpRanges': [{'CidrIp': '108.44.161.0/24'}]},
            {'IpProtocol': 'udp', 'FromPort': 500, 'ToPort': 500, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
            {'IpProtocol': 'udp', 'FromPort': 4500, 'ToPort': 4500, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
            {'IpProtocol': 'udp', 'FromPort': 4501, 'ToPort': 4501, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]}
        ]
    )

    # Create a private security group
    sg_private = ec2_client.create_security_group(
        GroupName=f"{name_prefix}PrivateSG",
        Description="Private Security Group",
        VpcId=vpc_id
    )

    # Add private security group rules (Allowing all RFC1918 traffic)
    for cidr in ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '108.44.161.0/24']:
        ec2_client.authorize_security_group_ingress(
            GroupId=sg_private['GroupId'],
            IpPermissions=[
                {'IpProtocol': '-1', 'FromPort': 0, 'ToPort': 65535, 'IpRanges': [{'CidrIp': cidr}]}
            ]
        )

    return sg_public['GroupId'], sg_private['GroupId']

# Function to create Network Interface
def create_network_interface(ec2_client, subnet_id, security_group_id):
    network_interface = ec2_client.create_network_interface(
        SubnetId=subnet_id,
        Groups=[security_group_id] 
    )
    return network_interface['NetworkInterface']['NetworkInterfaceId']


# Function to create elastic IP
def create_elastic_ip(ec2_client):
    eip = ec2_client.allocate_address(Domain='vpc')
    return eip['AllocationId']

# Function to associate elastic IP
def associate_elastic_ip(ec2_client, allocation_id, network_interface_id):
    ec2_client.associate_address(
        AllocationId=allocation_id,
        AllowReassociation= False,
        NetworkInterfaceId=network_interface_id
    )

# Function to create and configure EC2 instances
def deploy_ec2_instance(ec2_client, ami_id, instance_type, key_name, user_data, network_interfaces_config, instance_name):
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
    instance = ec2_client.run_instances(
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
                'Tags': [
                    {'Key': 'Name', 'Value': instance_name}
                ]
            }
        ],
        MetadataOptions={'HttpTokens': 'required'}
    )
    return instance['Instances'][0]['InstanceId']

def main():
    config = load_config('./config/config.yml')
    state = {} #Dictionary to keep track of Resource ID in a state file
    vm_count = {}  # Dictionary to keep track of VM count per region

    for region, region_config in config['aws']['Regions'].items():
        ec2_client = boto3.client('ec2', region_name=region)
        cf_client = boto3.client('cloudformation', region_name=region)

        # Retrieve VPC and Subnet IDs
        stack_name = config['aws']['StackName']
        region_outputs = get_cf_outputs(cf_client, stack_name)

        # Increment VM count for the region
        vm_count[region] = vm_count.get(region, 0) + 1

        # Prepare user_data with actual values
        user_data_formatted = config['aws']['EC2']['user_data'].format(
            NamePrefix=config['aws']['NamePrefix'] + region + f"-VM{vm_count[region]}",
            panorama_api_key=config['palo_alto']['panorama']['api_key'],
            panorama_ip_address1=config['palo_alto']['panorama']['ip_address1'],
            panorama_ip_address2=config['palo_alto']['panorama']['ip_address2'],
            PanoramaTemplate=config['palo_alto']['panorama']['PanoramaTemplate'],
            PanoramaDeviceGroup=config['palo_alto']['panorama']['PanoramaDeviceGroup']
        )
        # Convert user data to single line, semicolon-separated
        user_data_semi_colon_separated = user_data_formatted.replace('\n', ';').rstrip(';')
        # print(f'User-Data from config.yml: {user_data_formatted}')
        print(f'User-Data sent to EC2: {user_data_semi_colon_separated}')

        # Create Security Groups
        sg_public_id, sg_private_id = create_security_groups(ec2_client, region_outputs['VpcId'], config['aws']['NamePrefix'])

        # Define network interfaces configuration
        network_interfaces_config = [
            {'SubnetId': region_outputs['Subnet1Id'], 'SecurityGroupId': sg_public_id},
            {'SubnetId': region_outputs['Subnet2Id'], 'SecurityGroupId': sg_private_id},
            {'SubnetId': region_outputs['Subnet2Id'], 'SecurityGroupId': sg_private_id}
        ]

        # EC2 Settings
        ami_id = region_config['ngfw_ami_id']
        instance_type = config['aws']['EC2']['instance_type']
        key_name = region_config['key_name']
        
        # Define VM name
        vm_name = f"{config['aws']['NamePrefix']}{region}-VM{vm_count[region]}"

        # Deploy EC2 instance
        instance_id = deploy_ec2_instance(
            ec2_client,
            ami_id,
            instance_type,
            key_name,
            user_data_semi_colon_separated,
            network_interfaces_config,
            vm_name
        )
        # Wait for instance to be in running state (optional)
        ec2_client.get_waiter('instance_running').wait(InstanceIds=[instance_id])

        # Retrieve network interfaces and sort them by device index
        instance_info = ec2_client.describe_instances(InstanceIds=[instance_id])
        network_interfaces = instance_info['Reservations'][0]['Instances'][0]['NetworkInterfaces']
        sorted_network_interfaces = sorted(network_interfaces, key=lambda ni: ni['Attachment']['DeviceIndex'])

        # Record the created resources in the state dictionary
        state[region] = state.get(region, {})
        state[region][instance_id] = {
            'vm_name': vm_name,
            'SecurityGroups': {'Public': sg_public_id, 'Private': sg_private_id},
            'NetworkInterfaces': [],
            'ElasticIPs': []
        }
        # Create and associate Elastic IPs to the first two network interfaces (with indexes 0 and 1)
        for ni in sorted_network_interfaces[:2]:
            ni_id = ni['NetworkInterfaceId']
            eip_alloc_id = create_elastic_ip(ec2_client)
            associate_elastic_ip(ec2_client, eip_alloc_id, ni_id)
            
            # Get public IP for the EIP
            eip_info = ec2_client.describe_addresses(AllocationIds=[eip_alloc_id])
            public_ip = eip_info['Addresses'][0]['PublicIp']

            state[region][instance_id]['ElasticIPs'].append({
                'AllocationId': eip_alloc_id,
                'InterfaceId': ni_id,
                'PublicIP': public_ip
            })
        # Create additional state file information
        for ni in sorted_network_interfaces:
            subnet_info = ec2_client.describe_subnets(SubnetIds=[ni['SubnetId']])
            subnet_cidr = subnet_info['Subnets'][0]['CidrBlock']
            # Calculate Default Gateway (second IP in the subnet)
            subnet_network = ipaddress.ip_network(subnet_cidr)
            default_gw = str(next(subnet_network.hosts()))
            # Calculate PrivateIpCidr
            private_ip_cidr = f"{ni['PrivateIpAddress']}/{subnet_network.prefixlen}"
            state[region][instance_id]['NetworkInterfaces'].append({
                'InterfaceId': ni['NetworkInterfaceId'],
                'DeviceIndex': ni['Attachment']['DeviceIndex'],
                'PrivateIpAddress': ni['PrivateIpAddress'],
                'DefaultGW': default_gw,
                'PrivateIpCidr': private_ip_cidr
            })
        
        print(f"EC2 Instance created in {region}: {instance_id}")

    # Write the state information to a file
    with open('./state/state-ec2.json', 'w') as f:
        json.dump(state, f, indent=4)

if __name__ == '__main__':
    main()