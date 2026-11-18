import 'package:flutter/material.dart';
import '../model/catalog.dart';
import '../model/labels.dart';
import 'theme.dart';

class ExerciseTile extends StatelessWidget {
  final Json exercise;
  final int index;
  final bool selected;
  final VoidCallback inspect;
  final VoidCallback? up, down;
  const ExerciseTile(
    this.exercise,
    this.index,
    this.selected,
    this.inspect,
    this.up,
    this.down, {
    super.key,
  });
  @override
  Widget build(BuildContext context) => Card(
    color: selected ? const Color(0xff31343a) : panel,
    margin: const EdgeInsets.only(bottom: 6),
    child: ListTile(
      onTap: inspect,
      leading: Text(
        (index + 1).toString().padLeft(2, '0'),
        style: const TextStyle(color: yellow, fontWeight: FontWeight.bold),
      ),
      title: Text(exerciseLabel(exercise['kind'])),
      subtitle: Text(
        '№${exercise['id']}  ·  ${durationLabel(exercise['durationMinutes'])}',
      ),
      trailing: Wrap(
        children: [
          IconButton(
            tooltip: 'Выше',
            onPressed: up,
            icon: const Icon(Icons.keyboard_arrow_up),
          ),
          IconButton(
            tooltip: 'Ниже',
            onPressed: down,
            icon: const Icon(Icons.keyboard_arrow_down),
          ),
        ],
      ),
    ),
  );
}
