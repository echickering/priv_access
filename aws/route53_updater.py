import boto3
import logging
import re
import ipaddress

class Route53Updater:

    # Region-to-geographic identifier mappings
    REGION_GEO_IDENTIFIER_MAPPING = {
        'us-gov-east-1': 'us-goveast',
        'us-gov-west-1': 'us-govwest',
        'us-west-1': 'us-nocal',
        'us-west-2': 'us-oregon',
        'us-west-2-den-1a': 'us-denver',
        'us-west-2-las-1a': 'us-vegas',
        'us-west-2-lax-1a': 'us-lax',
        'us-west-2-lax-1b': 'us-lax',
        'us-west-2-phx-2a': 'us-phoenix',
        'us-west-2-pdx-1a': 'us-portland',
        'us-west-2-sea-1a': 'us-seattle',
        'us-east-1': 'us-va',
        'us-east-1-chi-2a': 'us-chicago',
        'us-east-1-dfw-2a': 'us-dallas',
        'us-east-1-atl-1a': 'us-atlanta',
        'us-east-1-bos-1a': 'us-boston',
        'us-east-1-iah-2a': 'us-houston',
        'us-east-1-mci-1a': 'us-kansas',
        'us-east-1-mia-1a': 'us-miami',
        'us-east-1-msp-1a': 'us-minneapolis',
        'us-east-1-nyc-1a': 'us-nyc',
        'us-east-1-phl-1a': 'us-philly',
        'us-east-2': 'us-ohio',        
        'af-south-1': 'af-capetown',
        'ap-east-1': 'apac-hongkong',
        'ap-south-2': 'apac-hyderabad',
        'ap-southeast-1': 'apac-singapore',
        'ap-southeast-2': 'apac-sydney',
        'ap-southeast-3': 'apac-jakarta',
        'ap-southeast-4': 'apac-melbourne',
        'ap-south-1': 'apac-mumbai',
        'ap-northeast-1': 'apac-tokyo',
        'ap-northeast-2': 'apac-seoul',
        'ap-northeast-3': 'apac-osaka',
        'ca-central-1': 'ca-central',
        'ca-west-1': 'ca-calgary',
        'eu-central-1': 'eu-frankfurt',
        'eu-central-2': 'eu-zurich',
        'eu-west-1': 'eu-ireland',
        'eu-west-2': 'eu-london',
        'eu-west-3': 'eu-paris',
        'eu-south-1': 'eu-milan',
        'eu-south-2': 'eu-spain',
        'eu-north-1': 'eu-stockholm',
        'il-central-1': 'il-telaviv',
        'me-south-1': 'me-bahrain',
        'me-central-1': 'me-uae',
        'sa-east-1': 'sa-saopaulo',

        # Add more mappings as needed
    }

    def __init__(self, aws_credentials, hosted_zone_id, domain):
        self.route53_client = boto3.client(
            'route53',
            aws_access_key_id=aws_credentials['access_key_id'],
            aws_secret_access_key=aws_credentials['secret_access_key']
        )
        self.hosted_zone_id = hosted_zone_id
        self.domain = domain

    def region_to_geoidentifier(self, region_az):
        # Try direct matching first
        if region_az in self.REGION_GEO_IDENTIFIER_MAPPING:
            return self.REGION_GEO_IDENTIFIER_MAPPING[region_az]

        # Attempt to extract and map the base region part
        base_region_match = re.match(r"^(us-east-1|us-east-2|us-west-1|us-west-2)", region_az)
        if base_region_match:
            base_region = base_region_match.group(0)
            return self.REGION_GEO_IDENTIFIER_MAPPING.get(base_region, 'unknown')

        # Fallback
        return 'unknown'
    
    def get_managed_geoidentifiers(self):
        # Return a view of all managed geographic identifiers from the class-level mapping
        return set(self.REGION_GEO_IDENTIFIER_MAPPING.values())

    def fetch_current_records(self):
        current_records = {}
        paginator = self.route53_client.get_paginator('list_resource_record_sets')
        for page in paginator.paginate(HostedZoneId=self.hosted_zone_id):
            for record_set in page['ResourceRecordSets']:
                if record_set['Type'] == 'A' and record_set['Name'].endswith(self.domain + '.'):
                    current_records[record_set['Name']] = record_set
        logging.debug(current_records)
        return current_records

    def update_dns_records(self, state_data):
        current_records = self.fetch_current_records()
        desired_records = self.prepare_desired_records(state_data)

        # First, delete records not present in the desired state
        self.remove_unmatched_records(current_records, desired_records)

        # Then, upsert records based on the desired state
        for geo_dns_name, ips in desired_records.items():
            self.upsert_weighted_a_records(geo_dns_name, ips)

    def prepare_geo_dns_mapping(self, state_data):
        geo_dns_mapping = {}
        for region_instance, data in state_data.items():
            geo_id = self.region_to_geoidentifier(region_instance.split('_')[0])
            geo_dns_name = f"{geo_id}.{self.domain}"  # Construct the geographical DNS name
            if geo_dns_name not in geo_dns_mapping:
                geo_dns_mapping[geo_dns_name] = []
            geo_dns_mapping[geo_dns_name].append(data['public_untrust_ip'])  # Append IP address
        return geo_dns_mapping

    def prepare_desired_records(self, state_data):
        """Prepare desired DNS records based on state data."""
        desired_records = {}
        for region_instance, data in state_data.items():
            geo_id = self.region_to_geoidentifier(region_instance.split('_')[0])
            geo_dns_name = f"{geo_id}.{self.domain}"
            if geo_dns_name not in desired_records:
                desired_records[geo_dns_name] = []
            ip = data['public_untrust_ip']
            if self.is_valid_ipv4(ip):
                desired_records[geo_dns_name].append(ip)
            else:
                logging.error(f"Invalid IPv4 address: {ip}")
        return desired_records

    def remove_unmatched_records(self, current_records, desired_records):
        managed_identifiers = self.get_managed_geoidentifiers()

        for record_name, record_data in current_records.items():
            # Check if record should be managed by the script
            if any(record_name.startswith(f"{identifier}.{self.domain}") for identifier in managed_identifiers):
                # Check if the record is not part of the desired state to decide on its deletion
                if record_name not in desired_records:
                    self.delete_record(record_name, record_data)

    def get_managed_identifiers(self):
        """Generate a set of all identifiers that are managed by the script, based on region_to_geoidentifier mappings."""
        managed_identifiers = set()
        for region_az in self.region_to_geoidentifier.keys():
            identifier = self.region_to_geoidentifier(region_az)
            if identifier != 'unknown':  # Exclude 'unknown' to avoid false positives
                managed_identifiers.add(identifier)
        return managed_identifiers

    def delete_record(self, record_name, record_data):
        # Ensure matching format with Route 53 records
        if record_name in record_data['Name']:
            changes = {
                'Changes': [{
                    'Action': 'DELETE',
                    'ResourceRecordSet': {
                        'Name': record_data['Name'],
                        'Type': record_data['Type'],
                        'TTL': record_data['TTL'],
                        'ResourceRecords': record_data['ResourceRecords']
                    }
                }]
            }

            # Check if 'Weight' and 'SetIdentifier' exist for weighted records.
            if 'Weight' in record_data and 'SetIdentifier' in record_data:
                changes['Changes'][0]['ResourceRecordSet']['Weight'] = record_data['Weight']
                changes['Changes'][0]['ResourceRecordSet']['SetIdentifier'] = record_data['SetIdentifier']

            # Debug: Log the change batch being submitted for deletion
            logging.debug(f"Submitting deletion for: {changes}")

            try:
                self.route53_client.change_resource_record_sets(
                    HostedZoneId=self.hosted_zone_id, ChangeBatch=changes)
                logging.debug(f"Deleted record: {record_name}")
            except Exception as e:
                logging.error(f"Failed to delete record {record_name}: {e}")

    def upsert_weighted_a_records(self, geo_dns_name, ips):
        """Upsert weighted A records."""
        for i, ip in enumerate(ips):
            unique_set_identifier = f"{geo_dns_name}-{i+1}"
            self.upsert_a_record(f"{geo_dns_name}.", ip, 100 // len(ips), unique_set_identifier)

    def upsert_a_record(self, name, value, weight, set_identifier):
        try:
            response = self.route53_client.change_resource_record_sets(
                HostedZoneId=self.hosted_zone_id,
                ChangeBatch={
                    'Changes': [{
                        'Action': 'UPSERT',
                        'ResourceRecordSet': {
                            'Name': name,
                            'Type': 'A',
                            'TTL': 60,
                            'Weight': weight,
                            'SetIdentifier': set_identifier,  # Use unique identifier here
                            'ResourceRecords': [{'Value': value}]
                        }
                    }]
                }
            )
            logging.info(f"Successfully upserted weighted A record: {name} ({set_identifier}) -> {value} with weight {weight}")
        except Exception as e:
            logging.error(f"Failed to upsert weighted A record {name} ({set_identifier}): {e}")

    def is_valid_ipv4(self, ip):
        try:
            ipaddress.ip_address(ip)
            return True
        except ValueError:
            return False