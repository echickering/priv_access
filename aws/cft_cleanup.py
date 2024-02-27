import boto3
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

class StackCleanup:
    def __init__(self, config, aws_credentials):
        self.config = config
        self.aws_credentials = aws_credentials
        self.session = boto3.Session(
            aws_access_key_id=aws_credentials['access_key_id'],
            aws_secret_access_key=aws_credentials['secret_access_key'],
            region_name=aws_credentials['default_region']
        )

    def get_all_regions(self):
        ec2 = self.session.client('ec2', region_name='us-east-1')
        regions = [region['RegionName'] for region in ec2.describe_regions()['Regions']]
        return regions

    def cleanup(self):
        if 'aws' in self.config and self.config['aws'].get('Regions'):
            defined_regions = self.config['aws'].get('Regions', {}).keys()
        else:
            defined_regions = []
        
        all_regions = self.get_all_regions()
        regions_to_check = set(all_regions) if not defined_regions else set(all_regions) - set(defined_regions)
        logging.info(f'Regions to check for cleanup: {regions_to_check}')

        with ThreadPoolExecutor() as executor:
            futures = {executor.submit(self.delete_stacks, region): region for region in regions_to_check}
            for future in as_completed(futures):
                region = futures[future]
                try:
                    future.result()
                except Exception as e:
                    logging.error(f"Error deleting stacks in {region}: {e}")

    def delete_stacks(self, region):
        cf = self.session.client('cloudformation', region_name=region)
        stack_names_in_order = [self.config['aws']['StackNameEC2'], self.config['aws']['StackNameVPC']]

        with ThreadPoolExecutor(max_workers=2) as executor:
            deletion_futures = []
            for stack_name in stack_names_in_order:
                future = executor.submit(self.delete_and_wait, cf, stack_name, region)
                deletion_futures.append(future)

            # Ensure both deletions are complete before moving on
            for future in as_completed(deletion_futures):
                try:
                    future.result()
                except Exception as e:
                    logging.error(f"Error during stack deletion/waiting in {region}: {e}")
                    raise

    def delete_and_wait(self, cf, stack_name, region):
        try:
            # First, check if the stack exists by trying to describe it
            cf.describe_stacks(StackName=stack_name)
            # If describe succeeds, it means the stack exists, so proceed with deletion
            cf.delete_stack(StackName=stack_name)
            logging.info(f"Initiated deletion of stack {stack_name} in {region}")  # Log as info because action is taking place
            
            # Wait for deletion to complete
            waiter = cf.get_waiter('stack_delete_complete')
            waiter.wait(StackName=stack_name)
            logging.info(f"Stack {stack_name} deletion completed in {region}")  # Log as info because action has completed
        except cf.exceptions.ClientError as e:
            if "does not exist" in str(e):
                logging.debug(f"Stack {stack_name} does not exist in {region}")  # Log as debug because it's a non-actionable situation
            else:
                logging.error(f"Error deleting stack {stack_name} in {region}: {e}")
                raise
