from lib.boto_adapter import AWSBotoAdapter


class StsAdapter:
    def __init__(self, profile, region):
        self.__connection = AWSBotoAdapter()
        self.__resource = 'sts'
        self.__profile = profile
        self.__region = region

    def __get_connection_sts(self):
        return self.__connection.get_client(self.__resource, self.__profile)

    def get_account_id(self):
        return self.__get_connection_sts().get_caller_identity()['Account']
