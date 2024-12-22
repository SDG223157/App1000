# app/data/data_service.p

import yfinance as yf
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from dateutil.relativedelta import relativedelta
from app.utils.config.metrics_config import METRICS_MAP, CAGR_METRICS
from sqlalchemy import create_engine, inspect
import os

class DataService:
    def __init__(self):
        """Initialize DataService with API and database configuration"""
        self.API_KEY = "a365bff224a6419fac064dd52e1f80d9"
        self.BASE_URL = "https://api.roic.ai/v1/rql"
        self.METRICS = METRICS_MAP
        self.CAGR_METRICS = CAGR_METRICS
        
        # Database configuration
        self.engine = create_engine(
            f"mysql+pymysql://{os.getenv('MYSQL_USER')}:"
            f"{os.getenv('MYSQL_PASSWORD')}@"
            f"{os.getenv('MYSQL_HOST')}:"
            f"{os.getenv('MYSQL_PORT', '3306')}/"
            f"{os.getenv('MYSQL_DATABASE')}"
        )

    def table_exists(self, table_name: str) -> bool:
        """Check if table exists in database"""
        try:
            inspector = inspect(self.engine)
            return table_name in inspector.get_table_names()
        except Exception as e:
            print(f"Error checking table existence: {e}")
            return False

    def store_dataframe(self, df: pd.DataFrame, table_name: str) -> bool:
        """Store DataFrame in database"""
        try:
            df.to_sql(
                name=table_name,
                con=self.engine,
                index=True,
                if_exists='replace',
                chunksize=10000
            )
            print(f"Successfully stored data in table: {table_name}")
            return True
        except Exception as e:
            print(f"Error storing DataFrame in table {table_name}: {e}")
            return False

    def get_historical_data_from_db(self, ticker: str) -> pd.DataFrame:
        """Retrieve historical data from database"""
        table_name = f"his_{ticker.lower()}"
        try:
            if self.table_exists(table_name):
                df = pd.read_sql_table(table_name, self.engine)
                df.set_index('Date', inplace=True)
                return df
            return None
        except Exception as e:
            print(f"Error retrieving historical data for {ticker}: {e}")
            return None

    def get_financial_data_from_db(self, ticker: str) -> pd.DataFrame:
        """Retrieve financial data from database"""
        table_name = f"roic_{ticker.lower()}"
        try:
            if self.table_exists(table_name):
                df = pd.read_sql_table(table_name, self.engine)
                return df
            return None
        except Exception as e:
            print(f"Error retrieving financial data for {ticker}: {e}")
            return None

    def store_historical_data(self, ticker: str, start_date: str = None, end_date: str = None) -> bool:
        """Fetch and store historical price data from yfinance"""
        try:
            print(f"Fetching historical data for {ticker} from yfinance")
            ticker_obj = yf.Ticker(ticker)
            
            # If no dates specified, get all available data
            if start_date and end_date:
                df = ticker_obj.history(start=start_date, end=end_date)
            else:
                df = ticker_obj.history(period="max")
            
            if df.empty:
                print(f"No historical data found for {ticker}")
                return False
            
            # Process the data
            df.index = df.index.tz_localize(None)
            table_name = f"his_{ticker.lower()}"
            
            # Store in database
            return self.store_dataframe(df, table_name)
            
        except Exception as e:
            print(f"Error storing historical data for {ticker}: {e}")
            return False

    def store_financial_data(self, ticker: str, start_year: str = None, end_year: str = None) -> bool:
        """Fetch and store financial data from ROIC API"""
        try:
            print(f"Fetching financial data for {ticker} from ROIC API")
            
            # If no years specified, use last 5 years
            if not start_year or not end_year:
                current_year = datetime.now().year
                end_year = str(current_year)
                start_year = str(current_year - 5)

            all_metrics_data = []
            
            # Fetch data for each metric
            for metric_description in self.METRICS:
                metric_field = self.METRICS[metric_description]
                query = f"get({metric_field}(fa_period_reference=range('{start_year}', '{end_year}'))) for('{ticker}')"
                url = f"{self.BASE_URL}?query={query}&apikey={self.API_KEY}"

                response = requests.get(url)
                response.raise_for_status()
                
                df = pd.DataFrame(response.json())
                if not df.empty:
                    df.columns = df.iloc[0]
                    df = df.drop(0).reset_index(drop=True)
                    all_metrics_data.append(df)

            if not all_metrics_data:
                print(f"No financial data found for {ticker}")
                return False

            # Combine all metrics data
            combined_df = pd.concat(all_metrics_data, axis=1)
            combined_df = combined_df.loc[:,~combined_df.columns.duplicated()]
            
            # Store in database
            table_name = f"roic_{ticker.lower()}"
            return self.store_dataframe(combined_df, table_name)
            
        except Exception as e:
            print(f"Error storing financial data for {ticker}: {e}")
            return False

    def get_or_fetch_historical_data(self, ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get historical data from database or fetch and store if not exists.
        Returns DataFrame with columns: Open, High, Low, Close, Volume
        """
        try:
            # Try to get from database first
            df = self.get_historical_data_from_db(ticker)
            
            # If not in database, fetch and store
            if df is None:
                success = self.store_historical_data(ticker, start_date, end_date)
                if success:
                    df = self.get_historical_data_from_db(ticker)
                
            if df is not None:
                # Filter for requested date range
                mask = (df.index >= start_date) & (df.index <= end_date)
                df = df[mask]
                
                if not df.empty:
                    required_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
                    return df[required_columns]
                
            # If still no data, fetch from yfinance directly
            ticker_obj = yf.Ticker(ticker)
            df = ticker_obj.history(start=start_date, end=end_date)
            
            if df.empty:
                raise ValueError(f"No data found for {ticker} in the specified date range")
            
            df.index = df.index.tz_localize(None)
            return df
                
        except Exception as e:
            print(f"Error fetching historical data for {ticker}: {str(e)}")
            raise

    def get_or_fetch_financial_data(self, ticker: str, metric_description: str, 
                                start_year: str, end_year: str) -> pd.Series:
        """
        Get financial data from database or fetch and store if not exists.
        Returns Series with years as index and metric values
        """
        try:
            # Try to get from database first
            df = self.get_financial_data_from_db(ticker)
            
            # If not in database, fetch and store
            if df is None:
                success = self.store_financial_data(ticker, start_year, end_year)
                if success:
                    df = self.get_financial_data_from_db(ticker)

            if df is not None:
                metric_field = self.METRICS.get(metric_description.lower())
                if metric_field in df.columns:
                    # Filter for requested years
                    df['fiscal_year'] = df['fiscal_year'].astype(int)
                    mask = (df['fiscal_year'] >= int(start_year)) & (df['fiscal_year'] <= int(end_year))
                    filtered_df = df[mask]
                    
                    if not filtered_df.empty:
                        return pd.Series(
                            filtered_df[metric_field].values,
                            index=filtered_df['fiscal_year'],
                            name=metric_description
                        )

            # If still no data, fetch from API directly
            metric_field = self.METRICS.get(metric_description.lower())
            if not metric_field:
                print(f"Warning: Unknown metric '{metric_description}', skipping...")
                return None

            query = f"get({metric_field}(fa_period_reference=range('{start_year}', '{end_year}'))) for('{ticker}')"
            url = f"{self.BASE_URL}?query={query}&apikey={self.API_KEY}"

            response = requests.get(url)
            response.raise_for_status()

            api_df = pd.DataFrame(response.json())
            if api_df.empty:
                return None

            api_df.columns = api_df.iloc[0]
            api_df = api_df.drop(0).reset_index(drop=True)

            years = api_df['fiscal_year'].astype(int)
            values = api_df[metric_field].astype(float)

            return pd.Series(values.values, index=years, name=metric_description)
                
        except Exception as e:
            print(f"Error fetching financial data for {ticker}: {str(e)}")
            return None

        # ... (keep other utility methods like calculate_returns, etc.)

    def get_historical_data(self, ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get historical data from MySQL database or yfinance if not exists.
        """
        table_name = f"his_{ticker.lower()}"
        
        try:
            # First try to get data from database
            if self.table_exists(table_name):
                print(f"Getting historical data for {ticker} from database")
                df = pd.read_sql_table(table_name, self.engine)
                df.set_index('Date', inplace=True)
                
                # Filter for requested date range
                mask = (df.index >= start_date) & (df.index <= end_date)
                filtered_df = df[mask]
                
                if not filtered_df.empty:
                    return filtered_df

            # If not in database, store it first
            print(f"Data not found in database for {ticker}, fetching from yfinance")
            success = self.store_historical_data(ticker, start_date, end_date)
            if success:
                # Get data from database after storing
                df = pd.read_sql_table(table_name, self.engine)
                df.set_index('Date', inplace=True)
                return df
            else:
                raise ValueError(f"Failed to store data for {ticker}")
                
        except Exception as e:
            print(f"Error in get_historical_data for {ticker}: {str(e)}")
            raise

    def get_financial_data(self, ticker: str, metric_description: str, 
                        start_year: str, end_year: str) -> pd.Series:
        """
        Get financial data from MySQL database or ROIC API if not exists.
        """
        table_name = f"roic_{ticker.lower()}"
        
        try:
            # First try to get data from database
            if self.table_exists(table_name):
                print(f"Getting financial data for {ticker} from database")
                df = pd.read_sql_table(table_name, self.engine)
                
                metric_field = self.METRICS.get(metric_description.lower())
                if metric_field in df.columns:
                    # Filter for requested years
                    df['fiscal_year'] = df['fiscal_year'].astype(int)
                    mask = (df['fiscal_year'] >= int(start_year)) & (df['fiscal_year'] <= int(end_year))
                    filtered_df = df[mask]
                    
                    if not filtered_df.empty:
                        return pd.Series(
                            filtered_df[metric_field].values,
                            index=filtered_df['fiscal_year'],
                            name=metric_description
                        )

            # If not in database, store it first
            print(f"Data not found in database for {ticker}, fetching from API")
            success = self.store_financial_data(ticker, start_year, end_year)
            if success:
                # Get data from database after storing
                df = pd.read_sql_table(table_name, self.engine)
                metric_field = self.METRICS.get(metric_description.lower())
                df['fiscal_year'] = df['fiscal_year'].astype(int)
                
                return pd.Series(
                    df[metric_field].values,
                    index=df['fiscal_year'],
                    name=metric_description
                )
            else:
                return None
                
        except Exception as e:
            print(f"Error in get_financial_data for {ticker}: {str(e)}")
            return None
    def get_analysis_dates(self, end_date: str, lookback_type: str, 
                         lookback_value: int) -> str:
        """
        Calculate start date based on lookback period

        Parameters:
        -----------
        end_date : str
            End date in YYYY-MM-DD format
        lookback_type : str
            Type of lookback period ('quarters' or 'days')
        lookback_value : int
            Number of quarters or days to look back

        Returns:
        --------
        str
            Start date in YYYY-MM-DD format
        """
        try:
            # Handle None or empty end_date
            if not end_date:
                end_date = datetime.now().strftime("%Y-%m-%d")
                
            # Validate date format
            try:
                end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            except ValueError:
                print(f"Invalid date format: {end_date}, using current date")
                end_dt = datetime.now()
                
            if lookback_type == 'quarters':
                start_dt = end_dt - relativedelta(months=3*lookback_value)
            else:  # days
                start_dt = end_dt - relativedelta(days=lookback_value)
                
            return start_dt.strftime("%Y-%m-%d")
            
        except Exception as e:
            print(f"Error calculating analysis dates: {str(e)}")
            raise

    def create_metrics_table(self, ticker: str, metrics: list, 
                           start_year: str, end_year: str) -> pd.DataFrame:
        """
        Creates a combined table of all metrics with selective growth rates

        Parameters:
        -----------
        ticker : str
            Stock ticker symbol
        metrics : list
            List of metrics to fetch
        start_year : str
            Start year in YYYY format
        end_year : str
            End year in YYYY format

        Returns:
        --------
        pd.DataFrame or None
            DataFrame containing metrics and growth rates or None if no data available
        """
        data = {}
        growth_rates = {}

        for metric in metrics:
            metric = metric.lower()
            series = self.get_financial_data(ticker.upper(), metric, start_year, end_year)
            
            if series is not None:
                data[metric] = series

                # Calculate CAGR only for specified metrics
                if metric in self.CAGR_METRICS:
                    try:
                        first_value = series.iloc[0]
                        last_value = series.iloc[-1]
                        num_years = len(series) - 1
                        if num_years > 0 and first_value > 0 and last_value > 0:
                            growth_rate = ((last_value / first_value) ** (1 / num_years) - 1) * 100
                            growth_rates[metric] = growth_rate
                    except Exception as e:
                        print(f"Error calculating CAGR for {metric}: {str(e)}")
                        growth_rates[metric] = None

        if data:
            try:
                # Create main DataFrame with metrics
                df = pd.DataFrame(data).T

                # Add growth rates column only for specified metrics
                df['CAGR %'] = None  # Initialize with None
                for metric in self.CAGR_METRICS:
                    if metric in growth_rates and metric in df.index:
                        df.at[metric, 'CAGR %'] = growth_rates[metric]

                return df
            except Exception as e:
                print(f"Error creating metrics table: {str(e)}")
                return None
        
        return None

    def calculate_returns(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate daily returns for a price series

        Parameters:
        -----------
        df : pd.DataFrame
            DataFrame containing price data

        Returns:
        --------
        pd.Series
            Series containing daily returns
        """
        try:
            if 'Close' not in df.columns:
                raise ValueError("Price data must contain 'Close' column")
                
            returns = df['Close'].pct_change()
            returns.fillna(0, inplace=True)
            return returns
            
        except Exception as e:
            print(f"Error calculating returns: {str(e)}")
            raise