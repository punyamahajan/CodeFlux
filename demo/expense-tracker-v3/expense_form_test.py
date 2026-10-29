import unittest
from expense_form import render_expense_form
from unittest.mock import MagicMock, patch

class TestExpenseForm(unittest.TestCase):
    def test_render_expense_form(self):
        expenses = []
        on_submit = MagicMock()
        
        with patch('streamlit.number_input') as mock_number_input:
            with patch('streamlit.text_input') as mock_text_input:
                with patch('streamlit.button') as mock_button:
                    render_expense_form(expenses, on_submit)
                    mock_number_input.assert_called_once()
                    mock_text_input.assert_called_once()
                    mock_button.assert_called_once()

if __name__ == '__main__':
    unittest.main()
