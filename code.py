
        def generate_template(
            dynamo_db_table: str,
            s3_bucket_name: str,
            iam_role_arn: str,
            opensearch_host: str,
            index_name: str,
            index_mapping: str
        ) -> str:template = f"""version: "2"
dynamodb-pipeline:
  source:
    dynamodb:
      acknowledgments: true
      tables:
        - table_arn: "${dynamo_db_table.tableArn}"
          # Remove the stream block if only export is needed
          stream:
            start_position: "LATEST"
          # Remove the export block if only stream is needed
          export:
            s3_bucket: "${s3_bucket_name}"
            s3_region: "eu-west-1"
            s3_prefix: "${dynamo_db_table.tableName}/"
      aws:
        sts_role_arn: "${iam_role_arn}"
        region: "eu-west-1"
  sink:
    - opensearch:
        hosts:
          [
            "https://${opensearch_host}",
          ]
        index: "${index_name}"
        index_type: "custom"
        template_content: |
          ${index_mapping}
        document_id: '\${getMetadata("primary_key")}'
        action: '\${getMetadata("opensearch_action")}'
        document_version: '\${getMetadata("document_version")}'
        document_version_type: "external"
        bulk_size: 4
        aws:
          sts_role_arn: "${iam_role_arn}"
          region: "eu-west-1"
          """
            
        index_name = "log-events"
        index_mapping = {
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 0
            },
            "mappings": {
                "properties": {
                    "id": {
                        "type": "keyword"
                    },
                    "timestamp": {
                        "type": "date",
                        "format": "epoch_millis"
                    }
                }
            }
        }

        pipeline_configuration_body = generate_template(
            dynamodb_table,
            s3_backup_bucket.bucket_name,
            opensearch_integration_pipeline_iam_role.role_arn,
            opensearch_domain.domain_endpoint,
            index_name,
            json.dumps(index_mapping)
        )

        cloudwatch_logs_group = logs.LogGroup(
            scope,
            "OpenSearch DynamoDB Ingestion Pipeline Log Group",
            log_group_name="/aws/vendedlogs/OpenSearchIntegration/opensearch-dynamodb-ingestion-pipeline",
            retention=logs.RetentionDays.ONE_MONTH
        )

        cfn_pipeline = osis.CfnPipeline(
            scope,
            "OpenSearch DynamoDB Ingestion Pipeline Configuration",
            max_units=4,
            min_units=1,
            pipeline_configuration_body=pipeline_configuration_body,
            pipeline_name="dynamodb-integration",
            log_publishing_options=osis.CfnPipeline.LogPublishingOptionsProperty(
                cloud_watch_log_destination=osis.CfnPipeline.CloudWatchLogDestinationProperty(
                    log_group=cloudwatch_logs_group.log_group_name
                ),
                is_logging_enabled=True
            )
        )
  