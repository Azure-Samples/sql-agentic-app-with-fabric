# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "f2b7ab5c-c086-435d-81a5-0554ccb3cb90",
# META       "default_lakehouse_name": "agentic_lake",
# META       "default_lakehouse_workspace_id": "d1a728f8-f435-46a7-9286-b10e12e92119",
# META       "known_lakehouses": [
# META         {
# META           "id": "f2b7ab5c-c086-435d-81a5-0554ccb3cb90"
# META         }
# META       ]
# META     }
# META   }
# META }

# CELL ********************

df = spark.read.parquet("Files/semantic_cache.parquet") 


df.write.mode("overwrite").format("delta").saveAsTable("cache_table")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

df = spark.sql("SELECT * FROM agentic_lake.cache_table LIMIT 1000")
display(df)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
