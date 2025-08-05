import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px
from datetime import datetime

# Streamlit page configuration
st.set_page_config(page_title="Sales Dashboard", layout="wide")

# Function to load data from Google Sheets
@st.cache_data
def load_data_from_sheets(credentials_dict):
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    credentials = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
    client = gspread.authorize(credentials)

    # Sales sheet IDs and names
    sales_sheets = [
        ("1Y0zoq6NODeLwOgftWwe4ooL687BTd24WRi9PO1GPmiA", "Master"),  # Jul-Sep 2025
        ("1QxhjtWwPsGrSUKZPD-tCNG9AnZ8wl2902vL1xAQsIaE", "Master"),  # Apr-Jun 2025
        ("1gSoF4Eox0C1UBk4aVy9SFi5uMAI2BWVdG3RKEcMljNI", "Master"),  # Oct-Dec 2024
        ("1nMvrCdTq3IJbuhoVcZzFsJzMGvZZG8U8q1x4Vn6Usvs", "Master"),  # Jan-Mar 2025
    ]

    # Load sales data
    sales_dfs = []
    for sheet_id, sheet_name in sales_sheets:
        sheet = client.open_by_key(sheet_id).worksheet(sheet_name)
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        print(f"Columns in sheet {sheet_id}:", df.columns.tolist())  # Debug column names
        sales_dfs.append(df)

    # Load product data
    product_sheet = client.open_by_key("1TehvfsbUaSMWxe6-XNW8hJNkGykDCN-KWjFN-79TmKQ").worksheet("Sheet1")
    product_data = product_sheet.get_all_records()
    product_df = pd.DataFrame(product_data)
    print("Columns in product sheet:", product_df.columns.tolist())  # Debug product sheet columns

    return sales_dfs, product_df

# Function to process and merge data
@st.cache_data
def process_data(sales_dfs, product_df):
    # Combine sales dataframes
    sales_df = pd.concat(sales_dfs, ignore_index=True)

    # Debug: Print raw Date values
    print("Raw Date values (first 10):", sales_df['Date'].head(10).tolist())
    print("Unique Date values (sample):", sales_df['Date'].unique()[:10])

    # Convert Item Id to string for merging
    sales_df['Item Id'] = sales_df['Item Id'].astype(str)
    product_df['Item Id'] = product_df['Item Id'].astype(str)

    # Convert Qty to numeric, coercing errors to NaN
    sales_df['Qty'] = pd.to_numeric(sales_df['Qty'], errors='coerce')
    # Convert Sale Price in product_df to numeric
    product_df['Sale Price'] = pd.to_numeric(product_df['Sale Price'], errors='coerce')

    # Debug: Print unique values
    print("Unique Qty values:", sales_df['Qty'].unique()[:10])
    print("Unique Sale Price values (product):", product_df['Sale Price'].unique()[:10])

    # Parse Date column (format: DD-MMM-YYYY)
    sales_df['Date'] = pd.to_datetime(sales_df['Date'], format="%d-%b-%Y", errors='coerce')

    # Debug: Check for NaT values
    nat_count = sales_df['Date'].isna().sum()
    if nat_count > 0:
        print(f"Found {nat_count} rows with NaT in Date column")
        nat_rows = sales_df[sales_df['Date'].isna()][['Date', 'Item Id', 'City', 'Qty']]
        print("Sample rows with NaT (showing original Date values):", nat_rows.to_dict())
        print("Unique invalid date values:", sales_df[sales_df['Date'].isna()]['Date'].unique().tolist())

    # Drop rows with NaT in Date column
    sales_df = sales_df.dropna(subset=['Date'])

    # Check if all rows were dropped
    if sales_df.empty:
        print("All rows dropped due to NaT in Date column. Check date formats in Google Sheets.")
        return pd.DataFrame()  # Return empty DataFrame to trigger error in main

    # Merge sales and product data on Item Id
    merged_df = pd.merge(sales_df,
                         product_df[['Item Id', 'DesiDiya - SKU', 'Category Name', 'Sub-Category Name', 'Sale Price', 'Platform']],
                         on='Item Id', how='left')

    # Calculate total sales, handling NaN values
    merged_df['Total Sales'] = merged_df['Qty'] * merged_df['Sale Price']

    # Fill NaN in Total Sales with 0
    merged_df['Total Sales'] = merged_df['Total Sales'].fillna(0)

    # Rename DesiDiya - SKU to Product Name for display
    merged_df = merged_df.rename(columns={'DesiDiya - SKU': 'Product Name'})

    # Debug: Print merged DataFrame info
    print("Merged DataFrame shape:", merged_df.shape)
    print("Merged DataFrame columns:", merged_df.columns.tolist())

    return merged_df

# Main dashboard
def main():
    st.title("Sales Dashboard")

    # Use Streamlit secrets for Google Sheets credentials
    try:
        credentials_dict = st.secrets["gcp_service_account"]
    except KeyError:
        st.error("Google Service Account credentials not found in secrets. Please configure secrets in Streamlit Community Cloud.")
        st.info("Add your Google Service Account JSON to the 'secrets.toml' in the Streamlit Cloud dashboard.")
        return

    try:
        # Load and process data
        with st.spinner("Loading data..."):
            sales_dfs, product_df = load_data_from_sheets(credentials_dict)
            df = process_data(sales_dfs, product_df)

        # Check if DataFrame is empty
        if df.empty:
            st.error("No valid data available after processing. Check date formats in Google Sheets.")
            st.info("Verify that the 'Date' column in all sales sheets uses the format DD-MMM-YYYY (e.g., 01-Jan-2025).")
            return

        # Check if all dates are NaT (shouldn't happen after dropna, but added for safety)
        if df['Date'].isna().all():
            st.error("All dates are invalid. Please check the 'Date' column in your Google Sheets.")
            return

        # Sidebar filters
        st.sidebar.header("Filters")
        cities = st.sidebar.multiselect("City", options=df['City'].unique(), default=df['City'].unique())
        categories = st.sidebar.multiselect("Category", options=df['Category Name'].unique(),
                                           default=df['Category Name'].unique())

        # Set default date range with safety checks
        min_date = df['Date'].min().date() if not df['Date'].isna().all() else datetime.today().date()
        max_date = df['Date'].max().date() if not df['Date'].isna().all() else datetime.today().date()
        try:
            date_range = st.sidebar.date_input(
                "Date Range",
                [min_date, max_date],
                min_value=min_date,
                max_value=max_date
            )
        except Exception as e:
            st.error(f"Error setting date range: {str(e)}")
            st.info("Ensure valid dates are present in the data.")
            return

        # Validate date_range length
        if len(date_range) != 2:
            st.warning("Please select a valid start and end date.")
            return

        # Filter data
        filtered_df = df[
            (df['City'].isin(cities)) &
            (df['Category Name'].isin(categories)) &
            (df['Date'].dt.date >= date_range[0]) &
            (df['Date'].dt.date <= date_range[1])
        ]

        # Check if filtered DataFrame is empty
        if filtered_df.empty:
            st.warning("No data matches the selected filters. Try adjusting the filters or check your data.")
            return

        # KPIs
        st.header("Key Performance Indicators")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            total_sales = filtered_df['Total Sales'].sum()
            st.metric("Total Sales", f"₹{total_sales:,.2f}")
        with col2:
            total_qty = filtered_df['Qty'].sum()
            st.metric("Total Quantity Sold", f"{total_qty:,}")
        with col3:
            total_orders = len(filtered_df)
            st.metric("Total Orders", f"{total_orders:,}")
        with col4:
            avg_selling_price = total_sales / total_qty if total_qty > 0 else 0
            st.metric("Average Selling Price", f"₹{avg_selling_price:,.2f}")

        # Original Charts
        st.header("Original Sales Analysis")
        # Sales by City
        st.subheader("Sales by City")
        city_sales = filtered_df.groupby('City')['Total Sales'].sum().reset_index()
        fig_city = px.bar(city_sales, x='City', y='Total Sales', title="Sales by City")
        st.plotly_chart(fig_city, use_container_width=True)

        # Sales by Category
        st.subheader("Sales by Category")
        category_sales = filtered_df.groupby('Category Name')['Total Sales'].sum().reset_index()
        fig_category = px.pie(category_sales, names='Category Name', values='Total Sales',
                              title="Sales by Category")
        st.plotly_chart(fig_category, use_container_width=True)

        # Platform filter for tables
        st.header("Detailed Sales Analysis")
        platforms = st.multiselect("Select Platforms for Tables", options=df['Platform'].unique(), default=df['Platform'].unique(), key="platform_filter")

        # Apply platform filter to filtered_df
        table_df = filtered_df[filtered_df['Platform'].isin(platforms)]
        if table_df.empty:
            st.warning("No data matches the selected platform filter. Adjust the platform selection.")
            return

        # Table 1: Product Name vs Platform (Qty and Total Sales)
        st.subheader("Table 1: Sales by Product and Platform")
        pivot_qty = table_df.pivot_table(values='Qty', index='Product Name', columns='Platform', aggfunc='sum', fill_value=0)
        pivot_sales = table_df.pivot_table(values='Total Sales', index='Product Name', columns='Platform', aggfunc='sum', fill_value=0)
        pivot_qty = pivot_qty.add_suffix(' (Qty)')
        pivot_sales = pivot_sales.add_suffix(' (Sales)')
        pivot_combined = pd.concat([pivot_qty, pivot_sales], axis=1)
        st.dataframe(pivot_combined, use_container_width=True)

        # Table 2: SKU (Product Name), Qty, Total Sales
        st.subheader("Table 2: Sales by SKU")
        sku_summary = table_df.groupby('Product Name').agg({'Qty': 'sum', 'Total Sales': 'sum'}).reset_index()
        st.dataframe(sku_summary, use_container_width=True)

        # Table 3: Sales by Platform Summary with Bar Chart
        st.subheader("Table 3: Sales by Platform Summary")
        platform_summary = table_df.groupby('Platform').agg({'Qty': 'sum', 'Total Sales': 'sum'}).reset_index()
        st.dataframe(platform_summary, use_container_width=True)
        fig_platform = px.bar(platform_summary, x='Platform', y=['Qty', 'Total Sales'], barmode='group', title="Sales by Platform")
        st.plotly_chart(fig_platform, use_container_width=True)

        # Table 4: Sales by Brand Summary with Bar Chart
        st.subheader("Table 4: Sales by Brand Summary")
        brand_summary = table_df.groupby('Brand').agg({'Qty': 'sum', 'Total Sales': 'sum'}).reset_index()
        st.dataframe(brand_summary, use_container_width=True)
        fig_brand = px.bar(brand_summary, x='Brand', y=['Qty', 'Total Sales'], barmode='group', title="Sales by Brand")
        st.plotly_chart(fig_brand, use_container_width=True)

        # Table 5: Monthly Sales Summary (below Sales Trend)
        st.subheader("Sales Trend Over Time")
        time_sales = table_df.groupby(table_df['Date'].dt.date)['Total Sales'].sum().reset_index()
        fig_time = px.line(time_sales, x='Date', y='Total Sales', title="Sales Trend")
        st.plotly_chart(fig_time, use_container_width=True)
        st.subheader("Table 5: Monthly Sales Summary")
        table_df['Month Name'] = table_df['Date'].dt.strftime('%B %Y')
        monthly_summary = table_df.groupby('Month Name').agg({'Qty': 'sum', 'Total Sales': 'sum'}).reset_index()
        monthly_summary = monthly_summary.sort_values(by='Month Name')
        st.dataframe(monthly_summary, use_container_width=True)

        # Table 6: Weekly Sales Summary (Monday to Sunday)
        st.subheader("Table 6: Weekly Sales Summary")
        table_df['Week Start'] = table_df['Date'].dt.to_period('W-MON').apply(lambda x: x.start_time)
        table_df['Month Week'] = table_df['Date'].dt.strftime('%B %Y') + ' Week ' + table_df['Date'].dt.isocalendar().week.astype(str)
        weekly_summary = table_df.groupby(['Month Week', 'Week Start']).agg({'Qty': 'sum', 'Total Sales': 'sum'}).reset_index()
        weekly_summary = weekly_summary.sort_values(by='Week Start')
        st.dataframe(weekly_summary[['Month Week', 'Qty', 'Total Sales']], use_container_width=True)

        # Table 7: Location (City) Wise Sales
        st.subheader("Table 7: Sales by Location")
        city_summary = table_df.groupby('City').agg({'Qty': 'sum', 'Total Sales': 'sum'}).reset_index()
        st.dataframe(city_summary, use_container_width=True)

        # Raw data option
        if st.checkbox("Show Raw Data"):
            st.subheader("Raw Data")
            st.warning(f"Displaying first 1000 rows of {len(table_df)} total rows to avoid performance issues.")
            st.dataframe(table_df[['Date', 'Item Id', 'City', 'Brand', 'Qty', 'Product Name', 'Category Name',
                                   'Sub-Category Name', 'Sale Price', 'Platform', 'Total Sales']].head(1000))
            csv = table_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="Download Full Data as CSV",
                data=csv,
                file_name="sales_data.csv",
                mime="text/csv"
            )

    except Exception as e:
        st.error(f"Error: {str(e)}")
        st.info("Check your JSON credentials, sheet access, date formats (DD-MMM-YYYY, e.g., 01-Jan-2025), or Item Id matching.")

if __name__ == "__main__":
    main()