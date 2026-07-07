import 'dart:async';
import 'package:flutter/material.dart';
import '../api/scenarios.dart';
import '../model/catalog.dart';
import 'feedback.dart';
import 'pager.dart';
import 'scenario_tile.dart';
import 'theme.dart';
class Library extends StatefulWidget{
 final Scenarios api;final int? selected;final ValueChanged<CatalogItem> open;
 const Library(this.api,this.selected,this.open,{super.key});
 @override State<Library> createState()=>_LibraryState();
}
class _LibraryState extends State<Library>{
 final search=TextEditingController();
 Timer? debounce;
 int offset=0;
 late Future<CatalogPage> result;
 @override void initState(){super.initState();result=widget.api.list('',0);}
 void load(int start){setState((){offset=start;result=widget.api.list(search.text,start);});}
 @override void dispose(){debounce?.cancel();search.dispose();super.dispose();}
 @override Widget build(BuildContext context)=>ColoredBox(color:panel,child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
 Padding(padding:const EdgeInsets.fromLTRB(16,20,16,12),child:Row(children:[Expanded(child:Text('Сценарии',style:Theme.of(context).textTheme.titleLarge)),IconButton(tooltip:'Обновить каталог',onPressed:()=>load(offset),icon:const Icon(Icons.refresh))])),
 Padding(padding:const EdgeInsets.symmetric(horizontal:14),child:TextField(controller:search,onChanged:(_){debounce?.cancel();debounce=Timer(const Duration(milliseconds:280),()=>load(0));},decoration:const InputDecoration(hintText:'Поиск сценария',prefixIcon:Icon(Icons.search)))),
 const SizedBox(height:12),Expanded(child:FutureBuilder<CatalogPage>(future:result,builder:(context,snap){
 if(snap.connectionState!=ConnectionState.done)return const Center(child:CircularProgressIndicator());
 if(snap.hasError)return Center(child:Padding(padding:const EdgeInsets.all(16),child:Column(mainAxisSize:MainAxisSize.min,children:[Text(errorText(snap.error!)),TextButton(onPressed:()=>load(offset),child:const Text('Повторить'))])));
 final page=snap.requireData;
 return Column(children:[Expanded(child:page.items.isEmpty?const Center(child:Text('Сценарии не найдены')):ListView.separated(itemCount:page.items.length,separatorBuilder:(_,_)=>const Divider(height:1),itemBuilder:(_,i){final item=page.items[i];return ScenarioTile(item,selected:item.id==widget.selected,onTap:()=>widget.open(item));})),Pager(offset,page.items.length,page.total,load)]);
 }))]));
}
