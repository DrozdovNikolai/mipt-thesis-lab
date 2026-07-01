import 'package:flutter/material.dart';
import '../model/catalog.dart';
import '../model/labels.dart';
import 'theme.dart';
class ScenarioTile extends StatelessWidget{
 final CatalogItem item; final bool selected; final VoidCallback onTap;
 const ScenarioTile(this.item,{required this.selected,required this.onTap,super.key});
 @override Widget build(BuildContext context)=>ListTile(selected:selected,selectedTileColor:yellow.withValues(alpha:0.08),onTap:onTap,
 title:Text(item.title,maxLines:2,overflow:TextOverflow.ellipsis,style:const TextStyle(fontWeight:FontWeight.w600)),subtitle:Text('${item.aircraft}  ·  ${statusLabel(item.status)}\n${item.modules} мод.  ·  ${durationLabel(item.minutes)}',style:const TextStyle(color:muted,height:1.6)),isThreeLine:true);
}
