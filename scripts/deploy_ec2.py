import boto3
import yaml
import base64
import json

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
    # Add public security group rules (modify as needed)
    # ec2_client.authorize_security_group_ingress(...)

    # Create a private security group
    sg_private = ec2_client.create_security_group(
        GroupName=f"{name_prefix}PrivateSG",
        Description="Private Security Group",
        VpcId=vpc_id
    )
    # Add private security group rules (modify as needed)
    # ec2_client.authorize_security_group_ingress(...)

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
        NetworkInterfaceId=network_interface_id
    )

# Function to create and configure EC2 instances
def deploy_ec2_instance(ec2_client, ami_id, instance_type, key_name, user_data, network_interfaces):
    # Specify the block device mapping (EBS volumes)
    block_device_mappings = [{
        'DeviceName': '/dev/xvda1',  # Adjust this based on AMI default
        'Ebs': {
            'VolumeSize': 60,  # Size in GB
            'VolumeType': 'gp3',
            'Encrypted': True,
            'DeleteOnTermination': True  # EBS volume is deleted on instance termination
        },
    }]

    # Update each network interface to set DeleteOnTermination
    for interface in network_interfaces:
        interface.update({'DeleteOnTermination': True})

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
        MetadataOptions={'HttpTokens': 'required'}
    )
    return instance['Instances'][0]['InstanceId']

def main():
    config = load_config('./config/config.yml')
    state = {}

    for region, region_config in config['aws']['Regions'].items():
        ec2_client = boto3.client('ec2', region_name=region)
        cf_client = boto3.client('cloudformation', region_name=region)

        # Retrieve VPC and Subnet IDs
        stack_name = config['aws']['StackName']
        region_outputs = get_cf_outputs(cf_client, stack_name)

        # Prepare user_data by replacing placeholders
        user_data_raw = config['aws']['EC2']['user_data'].format(
            NamePrefix=config['aws']['NamePrefix'],
            panorama_api_key=config['palo_alto']['panorama']['api_key'],
            panorama_ip_address1=config['palo_alto']['panorama']['ip_address1'],
            panorama_ip_address2=config['palo_alto']['panorama']['ip_address2'],
            PanoramaTemplate=config['palo_alto']['panorama']['PanoramaTemplate'],
            PanoramaDeviceGroup=config['palo_alto']['panorama']['PanoramaDeviceGroup']
        )
        user_data_encoded = base64.b64encode(user_data_raw.encode()).decode()
        print(f'UserData: {user_data_encoded}')
        # Create Security Groups
        sg_public_id, sg_private_id = create_security_groups(ec2_client, region_outputs['VpcId'], config['aws']['NamePrefix'])

        # Create Network Interfaces
        ni1_id = create_network_interface(ec2_client, region_outputs['Subnet1Id'], sg_public_id)
        ni2_id = create_network_interface(ec2_client, region_outputs['Subnet2Id'], sg_private_id)
        ni3_id = create_network_interface(ec2_client, region_outputs['Subnet2Id'], sg_private_id)

        # Create Elastic IP and associate it with the first network interface
        eip_alloc_id1 = create_elastic_ip(ec2_client)
        eip_alloc_id2 = create_elastic_ip(ec2_client)
        associate_elastic_ip(ec2_client, eip_alloc_id1, ni1_id)
        associate_elastic_ip(ec2_client, eip_alloc_id1, ni2_id)

        # Deploy EC2 instance
        user_data_encoded = base64.b64encode(config['aws']['EC2']['user_data'].encode()).decode()
        ami_id = region_config['ngfw_ami_id']
        instance_type = config['aws']['EC2']['instance_type']
        key_name = region_config['key_name']

        instance_id = deploy_ec2_instance(
            ec2_client,
            ami_id,
            instance_type,
            key_name,
            user_data_encoded,
            [{'NetworkInterfaceId': ni1_id, 'DeviceIndex': 0},
             {'NetworkInterfaceId': ni2_id, 'DeviceIndex': 1},
             {'NetworkInterfaceId': ni3_id, 'DeviceIndex': 2}]
        )       
        print(f"EC2 Instance created in {region}: {instance_id}")
        # Record the created resources in the state dictionary
        state[region] = {
            'SecurityGroups': {'Public': sg_public_id, 'Private': sg_private_id},
            'NetworkInterfaces': [ni1_id, ni2_id, ni3_id],
            'ElasticIPs': [eip_alloc_id1, eip_alloc_id2],
            'EC2InstanceId': instance_id
        }

    # Write the state information to a file
    with open('./state/state.json', 'w') as f:
        json.dump(state, f, indent=4)

if __name__ == '__main__':
    main()