# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "jupyter",
# META     "jupyter_kernel_name": "python3.11"
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

import duckdb
df = duckdb.sql("SELECT * FROM delta_scan('abfss://agentic_app_demo@onelake.dfs.fabric.microsoft.com/agentic_lake.Lakehouse/Tables/chat_history')").df()

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# CELL ********************

import pandas as pd
rag_ids = df.loc[df['tool_name'] == "search_support_documents"].trace_id.unique()
msg_types= ['ai', 'human']
sub_df = df[df['trace_id'].isin(rag_ids)]
contents = sub_df[sub_df['message_type'].isin(msg_types)]
cache_df = pd.DataFrame(columns = ['trace_id', 'question', 'answer'])

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# CELL ********************

j = 0
for i in contents.trace_id.unique().tolist():
    cache_df.loc[j,'trace_id'] = i
    cache_df.loc[j, 'question'] = contents[(contents['message_type'] == 'human') & (contents['trace_id']==i)].content.tolist()[0]
    cache_df.loc[j, 'answer'] = contents[(contents['message_type'] == 'ai')& (contents['trace_id']==i)].content.tolist()[0]
    j = j + 1

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# CELL ********************

cache_df

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# CELL ********************

cache_df.to_parquet("/lakehouse/default/Files/semantic_cache.parquet", index = False)


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# CELL ********************


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }
