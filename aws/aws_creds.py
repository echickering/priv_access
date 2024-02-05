import yaml

class AWSUtil:
    @staticmethod
    def load_aws_credentials(credentials_path='./config/aws_credentials.yml'):
        """
        Load AWS credentials from a specified YAML file.

        :param credentials_path: Path to the YAML file containing AWS credentials.
        :return: Dictionary with AWS credentials.
        """
        try:
            with open(credentials_path, 'r') as file:
                aws_credentials = yaml.safe_load(file)
                return aws_credentials['aws_credentials']
        except FileNotFoundError:
            raise Exception(f"Credentials file not found at {credentials_path}")
        except KeyError:
            raise Exception(f"Invalid format in credentials file at {credentials_path}")
