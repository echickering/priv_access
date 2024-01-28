import boto3
import yaml

def load_config(file_path):
    with open(file_path, 'r') as file:
        return yaml.safe_load(file)

def deploy_stack(cf_client, template_body, parameters):
    response = cf_client.create_stack(
        StackName='MyVPCStack',
        TemplateBody=template_body,
        Parameters=parameters,
        Capabilities=['CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM'],
        OnFailure='DELETE'  # Can be DO_NOTHING, ROLLBACK, or DELETE
    )
    return response

def main():
    config = load_config('./config/config.yml')
    aws_creds = load_config('./config/aws_credentials.yml')

    # Assuming aws_credentials are also part of config.yml under a separate key
    aws_credentials = aws_creds['aws_credentials']

    # Use the first region from the list
    region_name = config['aws']['regions'][0]

    boto3.setup_default_session(
        aws_access_key_id=aws_credentials['access_key_id'],
        aws_secret_access_key=aws_credentials['secret_access_key'],
        region_name=region_name
    )

    with open('config/vpc_template.yml', 'r') as file:
        template_body = file.read()

    cf_client = boto3.client('cloudformation')

    # Extracting parameters from config and formatting them for CF
    cf_parameters = [
        {
            'ParameterKey': 'VpcCidr',
            'ParameterValue': config['aws']['vpc']['vpc_cidr']
        },
        # Add this if you have added subnet CIDR in config
        {
            'ParameterKey': 'Subnet1Cidr',
            'ParameterValue': config['aws']['vpc']['subnet_cidr_block']
        }        
    ]

    response = deploy_stack(cf_client, template_body, cf_parameters)
    print(f"Stack creation initiated: {response['StackId']}")

if __name__ == '__main__':
    main()
