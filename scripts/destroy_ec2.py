import json
import boto3
import threading
from botocore.exceptions import ClientError

def terminate_region_resources(region, instances, data):
    ec2_client = boto3.client('ec2', region_name=region)
    instance_ids = list(instances.keys())  # Collect all instance IDs in this region

    if instance_ids:
        try:
            print(f"Terminating EC2 instances: {instance_ids} in {region}")
            ec2_client.terminate_instances(InstanceIds=instance_ids)
            waiter = ec2_client.get_waiter('instance_terminated')
            waiter.wait(InstanceIds=instance_ids)
            print(f"Instances {instance_ids} terminated.")

            for instance_id in list(instances.keys()):
                details = instances[instance_id]
                # Disassociate and release Elastic IPs
                for eip_alloc_id in details['ElasticIPs']:
                    try:
                        ec2_client.release_address(AllocationId=eip_alloc_id)
                        print(f"Released Elastic IP: {eip_alloc_id} in {region}")
                    except ClientError as e:
                        print(f"Error releasing EIP {eip_alloc_id}: {e}")

                # Delete Security Groups
                for sg_id in [details['SecurityGroups']['Public'], details['SecurityGroups']['Private']]:
                    try:
                        print(f"Deleting Security Group: {sg_id} in {region}")
                        ec2_client.delete_security_group(GroupId=sg_id)
                    except ClientError as e:
                        print(f"Error deleting Security Group {sg_id}: {e}")

                del data[region][instance_id]

            if not data[region]:  # Check if region has no more instances
                del data[region]  # Delete the region key

        except ClientError as e:
            print(f"Error processing instances in {region}: {e}")

def terminate_resources(datafile):
    with open(datafile, 'r') as file:
        data = json.load(file)

    threads = []
    for region, instances in data.items():
        thread = threading.Thread(target=terminate_region_resources, args=(region, instances, data))
        threads.append(thread)
        thread.start()

    # Wait for all threads to complete
    for thread in threads:
        thread.join()

    with open(datafile, 'w') as file:
        json.dump(data, file, indent=4)

    print("Resource termination process completed.")

if __name__ == "__main__":
    terminate_resources('./state/state-ec2.json')