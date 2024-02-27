import boto3
import logging
import re
import ipaddress

class Route53Updater:

    # Region-to-geographic identifier mappings
    REGION_GEO_IDENTIFIER_MAPPING = {
        'us-gov-east-1': 'us-goveast',
        'us-gov-west-1': 'us-govwest',
        'us-west-1': 'us-northcalifornia',
        'us-west-2': 'us-oregon',
        'us-west-2-den-1a': 'us-denver',
        'us-west-2-las-1a': 'us-vegas',
        'us-west-2-lax-1a': 'us-losangelesa',
        'us-west-2-lax-1b': 'us-losangelesb',
        'us-west-2-phx-2a': 'us-phoenix',
        'us-west-2-pdx-1a': 'us-portland',
        'us-west-2-sea-1a': 'us-seattle',
        'us-east-1': 'us-virginia',
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
        'us-east-1-bue-1a': 'sa-buenosaires',
        'us-east-1-lim-1a': 'sa-lima',
        'us-east-1-qro-1a': 'sa-queretaro',
        'us-east-1-scl-1a': 'sa-santiago',
        'us-east-2': 'us-ohio',        
        'af-south-1': 'af-capetown',
        'af-south-1-los-1a': 'af-lagos',
        'ap-east-1': 'apac-hongkong',
        'ap-southeast-1': 'apac-singapore',
        'ap-southeast-1-bkk-1a': 'apac-bangkok',
        'ap-southeast-1-mnl-1a': 'apac-manila',
        'ap-southeast-2': 'apac-sydney',
        'ap-southeast-2-akl-1a': 'apac-auckland',
        'ap-southeast-2-per-1a': 'apac-perth',
        'ap-southeast-3': 'apac-jakarta',
        'ap-southeast-4': 'apac-melbourne',
        'ap-south-1': 'apac-mumbai',
        'ap-south-1-del-1a': 'apac-delhi',
        'ap-south-1-ccu-1a': 'apac-kokata',
        'ap-south-2': 'apac-hyderabad',
        'ap-northeast-1': 'apac-tokyo',
        'ap-northeast-1-tpe-1a': 'apac-taipei',
        'ap-northeast-2': 'apac-seoul',
        'ap-northeast-3': 'apac-osaka',
        'ca-central-1': 'ca-central',
        'ca-west-1': 'ca-calgary',
        'eu-central-1': 'eu-frankfurt',
        'eu-central-1-ham-1a': 'eu-hamsburg',
        'eu-central-1-waw-1a': 'eu-warsaw',
        'eu-central-2': 'eu-zurich',
        'eu-west-1': 'eu-ireland',
        'eu-west-2': 'eu-london',
        'eu-west-3': 'eu-paris',
        'eu-south-1': 'eu-milan',
        'eu-south-2': 'eu-spain',
        'eu-north-1': 'eu-stockholm',
        'eu-north-1-cph-1a': 'eu-copenhagen',
        'eu-north-1-hel-1a': 'eu-helsinki',
        'il-central-1': 'il-telaviv',
        'me-south-1': 'me-bahrain',
        'me-south-1-mct-1a': 'me-muscat',
        'me-central-1': 'me-uae',
        'sa-east-1': 'sa-saopaulo',

        # Add more mappings as needed
    }

    def __init__(self, aws_credentials, config):
        self.route53_client = boto3.client(
            'route53',
            aws_access_key_id=aws_credentials['access_key_id'],
            aws_secret_access_key=aws_credentials['secret_access_key']
        )
        self.config = config
        self.hosted_zone_id = self.config['aws']['hosted_zone_id']
        self.domain = self.config['aws']['domain']
        self.portal_domain = self.config['aws']['portal_fqdn']

    def region_to_geoidentifier(self, region_az):
        # Try direct matching first
        if region_az in self.REGION_GEO_IDENTIFIER_MAPPING:
            return self.REGION_GEO_IDENTIFIER_MAPPING[region_az]

        # Attempt to extract and map the base region part
        base_region_match = re.match(r"^(us-east-1|us-east-2|us-west-1|us-west-2|ap-south-1|ap-northeast-3|ap-northeast-2|ap-southeast-1|ap-southeast-2|ap-northeast-1|ca-central-1|eu-central-1|eu-west-1|eu-west-2|eu-west-3|eu-north-1|sa-east-1|sa-east-1|af-south-1|ap-east-1|ap-south-2|ap-southeast-3|ap-southeast-4|ca-west-1|eu-south-1|eu-south-2|eu-central-2|me-south-1|me-central-1|il-central-1)", region_az)
        if base_region_match:
            base_region = base_region_match.group(0)
            return self.REGION_GEO_IDENTIFIER_MAPPING.get(base_region, 'unknown')

        # Fallback
        return 'unknown'

    def fetch_current_records(self):
        current_records = {}
        paginator = self.route53_client.get_paginator('list_resource_record_sets')
        for page in paginator.paginate(HostedZoneId=self.hosted_zone_id):
            for record_set in page['ResourceRecordSets']:
                if record_set['Type'] == 'A' and record_set['Name'].endswith(self.domain + '.'):
                    # Construct a unique key for each record set variation
                    record_key = record_set['Name']
                    if 'SetIdentifier' in record_set:
                        record_key += record_set['SetIdentifier']
                    current_records[record_key] = record_set
        logging.info(current_records)
        return current_records

    def update_dns_records(self, state_data):
        """
        Main method that is called by your main.py script. It fetches all current records, prepares desired records
        and removes orphaned records that match Portal or Gateway subdomains
        """
        current_records = self.fetch_current_records()
        desired_records = self.prepare_desired_records(state_data)
        
        # Identify and remove records not matching the desired state
        self.remove_orphaned_records(current_records, desired_records)

        portal_ips = []  # Aggregate IPs for the portal domain
        for geo_dns_name, ips in desired_records.items():
            self.upsert_weighted_a_records(geo_dns_name, ips)
            portal_ips.extend(ips)  # Collect IPs for each region

        # Now handle the portal domain separately
        self.upsert_portal_domain_records(portal_ips)

    def remove_orphaned_records(self, current_records, desired_records):
        """
        Remove DNS records that are no longer needed or represent decommissioned regions,
        while preserving records unrelated to the portal domain or geographic identifiers.
        """
        # Collect all DNS names that are actively managed by this script based on REGION_GEO_IDENTIFIER_MAPPING.
        managed_dns_names = {f"{geo_id}.{self.domain}." for geo_id in self.REGION_GEO_IDENTIFIER_MAPPING.values()}

        # Include portal domain records in managed DNS names.
        managed_dns_names.add(f"{self.portal_domain}.")

        # Iterate over current records to identify orphaned records.
        for current_record_key, record_data in current_records.items():
            # Check if the record is a managed DNS name or a portal domain record.
            is_managed_record = any(current_record_key.startswith(managed_name) for managed_name in managed_dns_names)
            
            # Extract record's base name (excluding set identifier) for comparison.
            record_base_name = current_record_key.rsplit('.', 2)[0] + '.'

            # Determine if the record is orphaned.
            is_orphaned_record = is_managed_record and record_base_name not in desired_records

            if is_orphaned_record:
                logging.info(f"Found orphaned record: {current_record_key}, scheduling for deletion.")
                self.delete_record(current_record_key, record_data)

    def delete_record(self, record_key, record_data):
        """
        Delete a specific DNS record from Route 53.
        """
        try:
            change_batch = {
                'Changes': [{
                    'Action': 'DELETE',
                    'ResourceRecordSet': record_data
                }]
            }
            self.route53_client.change_resource_record_sets(
                HostedZoneId=self.hosted_zone_id,
                ChangeBatch=change_batch
            )
            logging.info(f"Successfully deleted record: {record_key}")
        except Exception as e:
            logging.error(f"Error deleting record {record_key}: {e}")

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

    def get_managed_identifiers(self):
        """Generate a set of all identifiers that are managed by the script, based on region_to_geoidentifier mappings."""
        managed_identifiers = set()
        for region_az in self.region_to_geoidentifier.keys():
            identifier = self.region_to_geoidentifier(region_az)
            if identifier != 'unknown':  # Exclude 'unknown' to avoid false positives
                managed_identifiers.add(identifier)
        return managed_identifiers

    def upsert_weighted_a_records(self, geo_dns_name, ips):
        """Upsert weighted A records."""
        for i, ip in enumerate(ips):
            unique_set_identifier = f"{geo_dns_name}-{i+1}"
            self.upsert_a_record(f"{geo_dns_name}.", ip, 100 // len(ips), unique_set_identifier)

    def upsert_portal_domain_records(self, ips):
        """Upsert weighted A records for the portal domain."""
        for i, ip in enumerate(ips):
            unique_set_identifier = f"{self.portal_domain}-{i+1}"
            self.upsert_a_record(self.portal_domain, ip, 100, unique_set_identifier)

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