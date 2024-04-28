from aws_cdk import (
    aws_s3 as s3,
    aws_iam as iam,
    Stack,
    RemovalPolicy,
    aws_dynamodb as dynamodb,
    aws_opensearchservice as opensearch,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_cognito as cognito,
    aws_logs as logs,
    aws_datapipeline as datapipeline,
    aws_osis as osis

)
from constructs import Construct

class DashboardStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        REGION_NAME = self.region


        #create a cognito pool for opensearsh 
        cognito_pool = cognito.UserPool(self, "CognitoUserPool",
                                        sign_in_aliases=cognito.SignInAliases(
                                            email=True,
                                        ),
                                        auto_verify=cognito.AutoVerifiedAttrs(
                                            email=True
                                        ),
                                        standard_attributes=cognito.StandardAttributes(
                                            email=cognito.StandardAttribute(mutable=True, required=True)
                                        )
                                        )
        #create a identity pool for opensearch
        cognito_identity_pool = cognito.CfnIdentityPool(self, "CognitoIdentityPool",
                                                         allow_unauthenticated_identities=False,
                                                         cognito_identity_providers=[
                                                             cognito.CfnIdentityPool.CognitoIdentityProviderProperty(
                                                                 client_id=cognito_pool.user_pool_client_id,
                                                                 provider_name=cognito_pool.user_pool_provider_name
                                                             )
                                                         ]
                                                         )

        # Crea un rol de IAM para acceder al dominio de OpenSearch
        access_role = iam.Role(self, "OpenSearchAccessRole",
                               assumed_by=iam.AccountRootPrincipal())

        # Crea una política de acceso

        access_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "es:ESHttpGet",
                "es:ESHttpPost",
                "es:ESHttpPut",
                "es:ESHttpDelete",
                "ec2:DescribeVpcs",
                "cognito-identity:ListIdentityPools",
                "cognito-idp:ListUserPools",
                "iam:CreateRole",
                "iam:AttachRolePolicy"
            ],
            resources=[f"arn:aws:es:{self.region}:{self.account}:domain/ZeroETLDashboard/*"]
        )

        # Importar una VPC existente por su ID
          #vpc_id = "vpc-0d815c4380ab00166"  # Reemplaza con el ID de tu VPC existente
          #vpc = ec2.Vpc.from_lookup(self, "ImportedVPC", vpc_id=vpc_id, region="us-east-1")


        opensearch_domain = opensearch.Domain(self, "ZeroETLDashboardDemo",
                                   version=opensearch.EngineVersion.OPENSEARCH_1_3,
                                   capacity=opensearch.CapacityConfig(
                                       data_nodes=3,
                                       data_node_instance_type="r5.large.search",
                                       master_nodes=3,
                                       master_node_instance_type="r5.large.search"
                                   ),
                                   ebs=opensearch.EbsOptions(
                                       enabled=True,
                                       volume_size=100, 
                                       volume_type=ec2.EbsDeviceVolumeType.GP3
                                   ),
                                   zone_awareness=opensearch.ZoneAwarenessConfig(
                                       availability_zone_count=3
                                   ),

                                     #vpc=vpc,
                                     #vpc_subnets=[ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE)],
                                   access_policies=[
                                       access_policy
                                   ],
                                   cognito_dashboards_auth=True,
                                   cognito_identity_pool_id=cognito_identity_pool.ref,
                                   removal_policy=RemovalPolicy.DESTROY
                                   )
                                   
        
        s3_backup_bucket = s3.Bucket(
            self,
            "OpenSearchDynamoDBIngestionBackupS3Bucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            bucket_name="opensearch-ddb-ingestion-backup-v2",
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=True,
            removal_policy=RemovalPolicy.DESTROY
            
        )
        dynamodb_table = dynamodb.Table(
            self,
            "DynamoDBTable",
            partition_key=dynamodb.Attribute(
                name="id",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp",
                type=dynamodb.AttributeType.NUMBER
            ),
            table_name="opensearch-ingestion-table",
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery=True,
            stream=dynamodb.StreamViewType.NEW_IMAGE,
            removal_policy=RemovalPolicy.DESTROY
        )

        #create a Role with access to the opensearch domain, assume that has the necessary permissions to DynamoDB, OpenSearch, and S3. This role should have a trust relationship with osis-pipelines.amazonaws.com and opensearchservice.amazonaws.com
        sts_role = iam.Role(self, "OpenSearchIngestionRole",
                        assumed_by=[iam.ServicePrincipal("lambda.amazonaws.com"),
                                    iam.ServicePrincipal("opensearchservice.amazonaws.com")],
                        managed_policies=[
                            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonDynamoDBFullAccess"),
                            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonOpenSearchServiceFullAccess"),
                            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonS3FullAccess"),
                            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonOpenSearchIngestionFullAccess")
                        ]
                        )
        
        cloudwatch_logs_group = logs.LogGroup(
            scope,
            "OpenSearch DynamoDB Ingestion Pipeline Log Group",
            log_group_name="/aws/vendedlogs/OpenSearchIntegration/opensearch-dynamodb-ingestion-pipeline",
            retention=logs.RetentionDays.ONE_MONTH
        )

        
        #create the pipeline configuration
        def generate_template(dynamo_db_table,s3_backup_bucket, sts_role, opensearch_domain,REGION_NAME):
            template = f'''version: "2"
                dynamodb-pipeline:
                source:
                    dynamodb:
                    acknowledgments: true
                    tables:
                        - table_arn: "{dynamo_db_table.tableArn}"
                        # Remove the stream block if only export is needed
                        stream:
                            start_position: "LATEST"
                        # Remove the export block if only stream is needed
                        export:
                            s3_bucket: "{s3_backup_bucket.bucket_name}"
                            s3_region: "{REGION_NAME}"
                            s3_prefix: "ddb-to-opensearch-export/"
                    aws:
                        sts_role_arn: "{sts_role.role_arn}"
                        region: "{REGION_NAME}"
                sink:
                    - opensearch:
                        hosts:
                        [
                            "{opensearch_domain.domain_endpoint}",
                        ]
                        index: "table-index"
                        index_type: custom
                        document_id: \'${getMetadata("primary_key")}\'
                        action:  \'${getMetadata("opensearch_action")}\'
                        document_version:  \'${getMetadata("document_version")}\'
                        document_version_type: "external"
                        aws:
                            # REQUIRED: Provide a Role ARN with access to the domain. This role should have a trust relationship with osis-pipelines.amazonaws.com
                            sts_role_arn: "{sts_role.role_arn}"
                            # Provide the region of the domain.
                            region: "{REGION_NAME}"
            '''
            return template

        pipeline_configuration_body = generate_template(dynamodb_table,s3_backup_bucket, sts_role, opensearch_domain,REGION_NAME)

        


