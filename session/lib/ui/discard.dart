import 'package:flutter/material.dart';
Future<bool> confirmDiscard(BuildContext context) async=>await showDialog<bool>(context:context,builder:(ctx)=>AlertDialog(title:const Text('Отменить изменения?'),content:const Text('Порядок упражнений вернётся к сохранённой версии.'),actions:[
 TextButton(onPressed:()=>Navigator.pop(ctx,false),child:const Text('Продолжить работу')),
 FilledButton(onPressed:()=>Navigator.pop(ctx,true),child:const Text('Отменить изменения'))
]))??false;
