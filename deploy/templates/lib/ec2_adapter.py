from lib.boto_adapter import AWSBotoAdapter
from dateutil import parser

class Ec2Adapter:

    def __init__(self, profile, region):
        self.__connection = AWSBotoAdapter()
        self.__resource = 'ec2'
        self.__profile = profile
        self.__region = region

    def __get_connection_ec2(self):
        return self.__connection.get_client(self.__resource, self.__profile)

    def __get_newest_image(self, filters):
        images = self.__get_ami_list(filters)
        return self.__newest_image(images)

    def __get_ami_list(self, filters):
        return self.__get_connection_ec2().describe_images(Filters=filters)

    def __newest_image(self, list_of_images):
        latest = None
        for image in list_of_images['Images']:
            if not latest:
                latest = image
                continue
            if parser.parse(image['CreationDate']) > parser.parse(latest['CreationDate']):
                latest = image
        return latest['ImageId']

    def __get_all_subnets(self, vpcId):
        filters = [
            {'Name': 'vpc-id', 'Values': [vpcId]},
        ]
        subnets = []
        all_subnets = self.__get_connection_ec2().describe_subnets(Filters=filters)['Subnets']
        for subnet in all_subnets:
           subnets.append(subnet['SubnetId'])
        return subnets


    def get_latest_ami(self):
        filters = [{'Name': 'name', 'Values': ['amzn-ami-hvm-*']}]
        return self.__get_newest_image(filters)

    def get_available_subnets(self, vpcId):
       return self.__get_all_subnets(vpcId)


    def get_default_vpc(self):
        filters = [
            {'Name': 'isDefault', 'Values': ['true']}
        ]
        return self.__get_connection_ec2().describe_vpcs(Filters=filters)['Vpcs'][0]['VpcId']
