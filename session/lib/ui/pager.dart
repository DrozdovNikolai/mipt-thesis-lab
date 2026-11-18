import 'package:flutter/material.dart';
import '../api/scenarios.dart';

class Pager extends StatelessWidget {
  final int offset, count, total;
  final ValueChanged<int> change;
  const Pager(this.offset, this.count, this.total, this.change, {super.key});
  @override
  Widget build(BuildContext context) => Row(
    mainAxisAlignment: MainAxisAlignment.spaceBetween,
    children: [
      IconButton(
        tooltip: 'Предыдущая страница',
        onPressed: offset > 0
            ? () => change(offset - Scenarios.pageSize)
            : null,
        icon: const Icon(Icons.chevron_left),
      ),
      Text(
        count == 0
            ? '0 из $total'
            : '${offset + 1}–${offset + count} из $total',
      ),
      IconButton(
        tooltip: 'Следующая страница',
        onPressed: offset + count < total
            ? () => change(offset + Scenarios.pageSize)
            : null,
        icon: const Icon(Icons.chevron_right),
      ),
    ],
  );
}
