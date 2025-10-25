#!/bin/bash
# Billingonaire Test Runner
# Run all unit tests, integration tests, and e2e tests

echo "🧪 Running Billingonaire Test Suite..."
echo "========================================"
echo ""

# Run all tests with coverage
python -m pytest \
  tests/ \
  -v \
  --cov \
  --cov-report=html \
  --cov-report=term-missing \
  --tb=short

echo ""
echo "========================================"
echo "✅ Test execution complete!"
echo ""
echo "📊 Coverage report generated in htmlcov/index.html"
echo "📝 To view coverage: open htmlcov/index.html in your browser"
