import pandas as pd
import numpy as np

# Create test dataframe with Original_Release_Date and temp_sort_date
df = pd.DataFrame({
    'Folder_Name': ['A', 'B', 'C'],
    'Original_Release_Date': ['2020-01-01', '2021-01-01', '2022-01-01'],
    'Clean_Title': ['a', 'b', 'c']
})

df['temp_sort_date'] = pd.to_datetime(df['Original_Release_Date'], format='%Y-%m-%d', errors='coerce')
print("Before:")
print(df[['Folder_Name', 'Original_Release_Date', 'temp_sort_date']])

# Simulate patch_memory_df
folder_name = 'B'
new_data = {'Original_Release_Date': '2019-01-01'}

idx = df.index[df['Folder_Name'] == folder_name].tolist()
if idx:
    for k, v in new_data.items():
        if k in df.columns:
            df.at[idx[0], k] = str(v)
            if k == 'Original_Release_Date' and 'temp_sort_date' in df.columns:
                new_date_parsed = pd.to_datetime(v, format='%Y-%m-%d', errors='coerce')
                df.at[idx[0], 'temp_sort_date'] = new_date_parsed

print("\nAfter:")
print(df[['Folder_Name', 'Original_Release_Date', 'temp_sort_date']])

# Sort
df = df.sort_values(by='temp_sort_date', ascending=True, na_position='last')
print("\nSorted:")
print(df[['Folder_Name', 'Original_Release_Date', 'temp_sort_date']])
