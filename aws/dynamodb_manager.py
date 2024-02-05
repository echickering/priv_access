import boto3
import logging
from botocore.exceptions import ClientError

class DynamoDBManager:
    def __init__(self, aws_credentials, table_name="GlobalProtectUserPool"):
        self.aws_credentials = aws_credentials
        self.table_name = table_name
        self.dynamodb = boto3.resource('dynamodb',
                                       aws_access_key_id=self.aws_credentials['access_key_id'],
                                       aws_secret_access_key=self.aws_credentials['secret_access_key'],
                                       region_name='us-east-1')  # Adjust the region as necessary

    def create_table(self):
        try:
            table = self.dynamodb.create_table(
                TableName=self.table_name,
                KeySchema=[
                    {
                        'AttributeName': 'region',
                        'KeyType': 'HASH'  # Partition key
                    },
                    {
                        'AttributeName': 'subnet',
                        'KeyType': 'RANGE'  # Sort key
                    }
                ],
                AttributeDefinitions=[
                    {
                        'AttributeName': 'region',
                        'AttributeType': 'S'
                    },
                    {
                        'AttributeName': 'subnet',
                        'AttributeType': 'S'
                    },
                ],
                ProvisionedThroughput={
                    'ReadCapacityUnits': 5,
                    'WriteCapacityUnits': 5
                }
            )
            logging.info("Table creation in progress...")
            table.wait_until_exists()
            logging.info("Table created successfully.")
        except ClientError as e:
            logging.error(e.response['Error']['Message'])

    def update_subnet_allocation(self, region, subnet, allocation):
        table = self.dynamodb.Table(self.table_name)
        try:
            response = table.put_item(
               Item={
                    'region': region,
                    'subnet': subnet,
                    'allocation': allocation
                }
            )
            logging.info(f"Subnet allocation updated successfully: {response}")
        except ClientError as e:
            logging.error(e.response['Error']['Message'])

    def get_subnet_allocation(self, region, subnet):
        table = self.dynamodb.Table(self.table_name)
        try:
            response = table.get_item(
                Key={
                    'region': region,
                    'subnet': subnet
                }
            )
            return response['Item'] if 'Item' in response else None
        except ClientError as e:
            logging.error(e.response['Error']['Message'])
            return None

    def create_table_if_not_exists(self):
        # Check if the table already exists
        existing_tables = self.dynamodb.meta.client.list_tables()['TableNames']
        if self.table_name not in existing_tables:
            self.create_table()
        else:
            logging.info(f"Table '{self.table_name}' already exists.")