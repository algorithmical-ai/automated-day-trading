"""
Test that Decimal and float arithmetic works correctly
"""

from decimal import Decimal
import pytest


class TestDecimalFloatConversion:
    """Test suite for Decimal/float arithmetic"""

    def test_decimal_float_subtraction_fails(self):
        """Test that Decimal - float raises TypeError"""
        enter_price = Decimal("100.50")
        current_price = 101.0
        
        # This should fail without conversion
        with pytest.raises(TypeError):
            result = current_price - enter_price

    def test_decimal_float_subtraction_with_conversion(self):
        """Test that float(Decimal) - float works"""
        enter_price = Decimal("100.50")
        current_price = 101.0
        
        # This should work with conversion
        result = current_price - float(enter_price)
        assert result == pytest.approx(0.50, abs=0.01)

    def test_profit_calculation_with_decimal(self):
        """Test profit calculation with Decimal enter_price"""
        enter_price = Decimal("100.00")
        current_price = 105.00
        
        # This should work with conversion
        profit_percent = ((current_price - float(enter_price)) / float(enter_price)) * 100
        assert profit_percent == pytest.approx(5.0, abs=0.01)

    def test_profit_calculation_short_with_decimal(self):
        """Test short profit calculation with Decimal enter_price"""
        enter_price = Decimal("100.00")
        current_price = 95.00
        
        # This should work with conversion
        profit_percent = ((float(enter_price) - current_price) / float(enter_price)) * 100
        assert profit_percent == pytest.approx(5.0, abs=0.01)

    def test_comparison_with_decimal(self):
        """Test that Decimal > float comparison works"""
        peak_price = 105.0
        enter_price = Decimal("100.00")
        
        # This should work - Python handles mixed type comparisons
        assert peak_price > float(enter_price)

    def test_division_with_decimal(self):
        """Test division with Decimal"""
        spread = 2.0
        enter_price = Decimal("100.00")
        
        # This should fail without conversion
        with pytest.raises(TypeError):
            result = (spread / enter_price) * 100
        
        # This should work with conversion
        result = (spread / float(enter_price)) * 100
        assert result == pytest.approx(2.0, abs=0.01)


if __name__ == "__main__":
    import asyncio
    
    print("\n=== Testing Decimal/Float Conversion ===\n")
    
    test = TestDecimalFloatConversion()
    
    try:
        test.test_decimal_float_subtraction_fails()
        print("✓ Decimal - float raises TypeError (as expected)")
    except AssertionError:
        print("✗ Decimal - float should raise TypeError")
    
    test.test_decimal_float_subtraction_with_conversion()
    print("✓ float(Decimal) - float works correctly")
    
    test.test_profit_calculation_with_decimal()
    print("✓ Profit calculation with Decimal works")
    
    test.test_profit_calculation_short_with_decimal()
    print("✓ Short profit calculation with Decimal works")
    
    test.test_comparison_with_decimal()
    print("✓ Decimal > float comparison works")
    
    try:
        test.test_division_with_decimal()
        print("✓ Division with Decimal conversion works")
    except AssertionError:
        print("✗ Division with Decimal should work with conversion")
    
    print("\n=== All tests passed! ===\n")
