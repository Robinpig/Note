import unit_test
from calculator import Calculator


class TestCalculator(unit_test.TestCalculator):
    def test_add(self):
        c = Calculator(4, 6)
        result = c.__add__()
        self.assertEqual(result, 10)


if __name__ == '__main__':
    unit_test.main()
