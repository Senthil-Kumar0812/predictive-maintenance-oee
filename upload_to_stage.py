import snowflake.connector

conn = snowflake.connector.connect(connection_name="<YOUR_CONNECTION_NAME>")
cur = conn.cursor()
cur.execute("USE DATABASE PDM_OEE_DB")
cur.execute("USE SCHEMA GOLD")

# Upload streamlit_app.py
cur.execute(r"PUT 'file://<PATH_TO_PROJECT>/streamlit_app/streamlit_app.py' @PDM_OEE_DB.GOLD.STREAMLIT_STAGE/app AUTO_COMPRESS=FALSE OVERWRITE=TRUE")
print("Uploaded streamlit_app.py:", cur.fetchall())

conn.close()
print("Done.")
