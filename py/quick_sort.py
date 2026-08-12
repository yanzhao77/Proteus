def quick_sort(values):
    if len(values) <= 1:
        return values.copy()

    pivot = values[len(values) // 2]
    lower = [value for value in values if value < pivot]
    equal = [value for value in values if value == pivot]
    higher = [value for value in values if value > pivot]
    return quick_sort(lower) + equal + quick_sort(higher)


if __name__ == "__main__":
    numbers = [8, 3, 1, 7, 0, 10, 2, 3, -4]
    result = quick_sort(numbers)
    expected = sorted(numbers)

    assert result == expected, f"expected {expected}, got {result}"
    print(result)
    print("Quick sort verification passed.")
