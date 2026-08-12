def shell_sort(values):
    """Return a sorted copy of values using Shell sort."""
    items = list(values)
    gap = len(items) // 2

    while gap > 0:
        for index in range(gap, len(items)):
            current = items[index]
            position = index

            while position >= gap and items[position - gap] > current:
                items[position] = items[position - gap]
                position -= gap

            items[position] = current

        gap //= 2

    return items


if __name__ == "__main__":
    sample = [10, -4, 3, 7, 3, 0, 8, 1, 2]
    sorted_sample = shell_sort(sample)
    print(sorted_sample)
    assert sorted_sample == sorted(sample)
    print("Shell sort verification passed.")
