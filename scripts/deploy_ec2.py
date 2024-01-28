import boto3
import yaml

def load_config(file_path):
    with open(file_path, 'r') as file:
        return yaml.safe_load(file)

def get_vpc_subnet_ids(cf_client, stack_name):
    # Assuming VPC and Subnet IDs are defined as outputs in your CloudFormation stack
    stack = cf_client.describe_stacks(StackName=stack_name)['Stacks'][0]
    outputs = {o['OutputKey']: o['OutputValue'] for o in stack['Outputs']}
    return outputs['VpcId'], outputs['SubnetId']  # Replace with your actual output keys

def deploy_ec2_instances(ec2_client, vpc_id, subnet_id, config):
    # Deploy EC2 instances using the provided VPC and Subnet IDs
    # Add logic based on your specific EC2 requirements (AMI, instance type, etc.)
    pass

def main():
    config = load_config('./config/config.yml')

    for region, region_config in config['aws']['regions'].items():
        cf_client = boto3.client('cloudformation', region_name=region)
        ec2_client = boto3.client('ec2', region_name=region)

        vpc_id, subnet_id = get_vpc_subnet_ids(cf_client, config['aws']['StackName'])
        deploy_ec2_instances(ec2_client, vpc_id, subnet_id, config)

if __name__ == '__main__':
    main()
