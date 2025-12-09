"""
Tests for DynamoDB float to Decimal conversion in update_item
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal
from app.src.db.dynamodb_client import DynamoDBClient, _convert_floats_to_decimals


class TestFloatToDecimalConversion:
    """Test suite for float to Decimal conversion"""

    def test_convert_floats_to_decimals_simple_float(self):
        """Test converting a simple float to Decimal"""
        result = _convert_floats_to_decimals(1.5)
        assert isinstance(result, Decimal)
        assert result == Decimal('1.5')

    def test_convert_floats_to_decimals_dict_with_floats(self):
        """Test converting a dict with float values"""
        input_dict = {
            'price': 1.5,
            'profit': 2.75,
            'loss': -0.5
        }
        result = _convert_floats_to_decimals(input_dict)
        
        assert isinstance(result['price'], Decimal)
        assert isinstance(result['profit'], Decimal)
        assert isinstance(result['loss'], Decimal)
        assert result['price'] == Decimal('1.5')
        assert result['profit'] == Decimal('2.75')
        assert result['loss'] == Decimal('-0.5')

    def test_convert_floats_to_decimals_nested_dict(self):
        """Test converting nested dicts with floats"""
        input_dict = {
            'trade': {
                'enter_price': 1.5,
                'exit_price': 2.0,
                'profit': 0.5
            },
            'metrics': {
                'atr': 0.25,
                'rsi': 65.5
            }
        }
        result = _convert_floats_to_decimals(input_dict)
        
        assert isinstance(result['trade']['enter_price'], Decimal)
        assert isinstance(result['trade']['exit_price'], Decimal)
        assert isinstance(result['metrics']['atr'], Decimal)
        assert result['trade']['enter_price'] == Decimal('1.5')
        assert result['metrics']['rsi'] == Decimal('65.5')

    def test_convert_floats_to_decimals_list_with_floats(self):
        """Test converting a list with float values"""
        input_list = [1.5, 2.75, -0.5, 100.0]
        result = _convert_floats_to_decimals(input_list)
        
        assert all(isinstance(item, Decimal) for item in result)
        assert result[0] == Decimal('1.5')
        assert result[1] == Decimal('2.75')
        assert result[2] == Decimal('-0.5')
        assert result[3] == Decimal('100.0')

    def test_convert_floats_to_decimals_mixed_types(self):
        """Test converting mixed types (strings, ints, floats)"""
        input_dict = {
            'ticker': 'AAPL',
            'count': 5,
            'price': 1.5,
            'active': True,
            'tags': ['tech', 'large-cap']
        }
        result = _convert_floats_to_decimals(input_dict)
        
        assert result['ticker'] == 'AAPL'
        assert result['count'] == 5
        assert isinstance(result['price'], Decimal)
        assert result['price'] == Decimal('1.5')
        assert result['active'] is True
        assert result['tags'] == ['tech', 'large-cap']

    def test_convert_floats_to_decimals_preserves_non_floats(self):
        """Test that non-float values are preserved"""
        input_dict = {
            'string': 'value',
            'integer': 42,
            'boolean': True,
            'none': None,
            'float': 1.5
        }
        result = _convert_floats_to_decimals(input_dict)
        
        assert result['string'] == 'value'
        assert result['integer'] == 42
        assert result['boolean'] is True
        assert result['none'] is None
        assert isinstance(result['float'], Decimal)

    @pytest.mark.asyncio
    async def test_update_item_converts_floats_to_decimals(self):
        """Test that update_item converts float values to Decimals"""
        mock_table = AsyncMock()
        mock_table.update_item = AsyncMock(return_value=None)
        
        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table = AsyncMock(return_value=mock_table)
        
        # Create a proper async context manager mock
        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_dynamodb)
        mock_context.__aexit__ = AsyncMock(return_value=None)
        
        mock_session = AsyncMock()
        mock_session.resource = MagicMock(return_value=mock_context)
        
        client = DynamoDBClient()
        client.session = mock_session
        
        # Call update_item with float values
        result = await client.update_item(
            table_name='TestTable',
            key={'ticker': 'AAPL'},
            update_expression='SET price = :p, profit = :pr',
            expression_attribute_values={
                ':p': 1.5,
                ':pr': 2.75
            }
        )
        
        assert result is True
        
        # Verify that update_item was called with Decimal values
        mock_table.update_item.assert_called_once()
        call_args = mock_table.update_item.call_args
        
        # Check that the values were converted to Decimals
        expr_values = call_args[1]['ExpressionAttributeValues']
        assert isinstance(expr_values[':p'], Decimal)
        assert isinstance(expr_values[':pr'], Decimal)
        assert expr_values[':p'] == Decimal('1.5')
        assert expr_values[':pr'] == Decimal('2.75')

    @pytest.mark.asyncio
    async def test_update_item_converts_key_floats_to_decimals(self):
        """Test that update_item converts float values in keys to Decimals"""
        mock_table = AsyncMock()
        mock_table.update_item = AsyncMock(return_value=None)
        
        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table = AsyncMock(return_value=mock_table)
        
        # Create a proper async context manager mock
        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_dynamodb)
        mock_context.__aexit__ = AsyncMock(return_value=None)
        
        mock_session = AsyncMock()
        mock_session.resource = MagicMock(return_value=mock_context)
        
        client = DynamoDBClient()
        client.session = mock_session
        
        # Call update_item with float in key
        result = await client.update_item(
            table_name='TestTable',
            key={'ticker': 'AAPL', 'price': 1.5},
            update_expression='SET profit = :pr',
            expression_attribute_values={
                ':pr': 2.75
            }
        )
        
        assert result is True
        
        # Verify that the key was converted
        call_args = mock_table.update_item.call_args
        key = call_args[1]['Key']
        assert isinstance(key['price'], Decimal)
        assert key['price'] == Decimal('1.5')
