import 'package:flutter/material.dart';
import 'theme.dart';

class Brand extends StatelessWidget {
  const Brand({super.key});
  @override
  Widget build(BuildContext context) => const Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Icon(Icons.explore_outlined, color: yellow, size: 28),
      SizedBox(width: 8),
      Text(
        '55NORD',
        style: TextStyle(
          fontSize: 19,
          fontWeight: FontWeight.w900,
          letterSpacing: 1,
        ),
      ),
      SizedBox(width: 8),
      Text('Session', style: TextStyle(fontSize: 18, color: muted)),
    ],
  );
}
