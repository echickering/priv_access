import boto3
import yaml

def load_config(file_path):
    with open(file_path, 'r') as file:
        return yaml.safe_load(file)

def deploy_stack(cf_client, template_body, parameters, stack_name):
    try:
        print(f"Updating stack {stack_name}...")
        response = cf_client.update_stack(
            StackName=stack_name,
            TemplateBody=template_body,
            Parameters=parameters,
            Capabilities=['CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM']
        )
        return {"Status": "Update Initiated", "StackId": response['StackId']}
    except cf_client.exceptions.ClientError as error:
        if error.response['Error']['Message'] == 'No updates are to be performed.':
            print("No updates are to be performed.")
            return {"Status": "No Update Needed"}
        elif 'does not exist' in error.response['Error']['Message']:
            print(f"Creating stack {stack_name}...")
            response = cf_client.create_stack(
                StackName=stack_name,
                TemplateBody=template_body,
                Parameters=parameters,
                Capabilities=['CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM'],
                OnFailure='ROLLBACK'  # Recommended to use ROLLBACK for creation
            )
            return {"Status": "Creation Initiated", "StackId": response['StackId']}
        else:
            raise

def main():
    config = load_config('./config/config.yml')
    aws_creds = load_config('./config/aws_credentials.yml')
    aws_credentials = aws_creds['aws_credentials']
    name_prefix = config['aws']['NamePrefix']

    for region, region_config in config['aws']['Regions'].items():
        print(f"Deploying in region: {region}")
        vpc_name = name_prefix + region.replace('-', '')

        boto3.setup_default_session(
            aws_access_key_id=aws_credentials['access_key_id'],
            aws_secret_access_key=aws_credentials['secret_access_key'],
            region_name=region
        )

        with open('config/vpc_template.yml', 'r') as file:
            template_body = file.read()

        cf_client = boto3.client('cloudformation')
        cf_parameters = [
            {
                'ParameterKey': 'NamePrefix',
                'ParameterValue': config['aws']['NamePrefix']
            },
            {
                'ParameterKey': 'VpcName',
                'ParameterValue': vpc_name
            },
            {
                'ParameterKey': 'VpcCidr',
                'ParameterValue': region_config['vpc_cidr']
            },
            {
                'ParameterKey': 'Subnet1Cidr',
                'ParameterValue': region_config['subnet1_cidr_block']
            },
            {
                'ParameterKey': 'Subnet2Cidr',
                'ParameterValue': region_config['subnet2_cidr_block']
            }        
        ]

        result = deploy_stack(cf_client, template_body, cf_parameters, stack_name=config['aws']['StackName'])

        if result:
            if result['Status'] in ["Update Initiated", "Creation Initiated"]:
                print(f"Stack deployment initiated in {region}: {result['StackId']}")
            elif result['Status'] == "No Update Needed":
                print(f"No update was needed for the stack in {region}.")
        else:
            print(f"An unexpected error occurred in {region}.")

if __name__ == '__main__':
    main()
