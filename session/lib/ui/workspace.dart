import 'package:flutter/material.dart';
import '../api/profile.dart';
import '../api/scenarios.dart';
import '../model/catalog.dart';
import '../model/document.dart';
import 'brand.dart';
import 'details.dart';
import 'discard.dart';
import 'editor_header.dart';
import 'feedback.dart';
import 'library.dart';
import 'modules.dart';
import 'theme.dart';

class Workspace extends StatefulWidget{
 final Profile profile;
 final Scenarios api;
 final VoidCallback logout;
 const Workspace(this.profile,this.api,this.logout,{super.key});
 @override State<Workspace> createState()=>_WorkspaceState();
}
class _WorkspaceState extends State<Workspace>{
 Document? doc;
 Json? selected;
 bool busy=false;
 bool saving=false;
 bool get editable=>widget.profile.canEdit && doc?.data['status']?.toString().toUpperCase()=='DRAFT';
 @override Widget build(BuildContext context)=>const Scaffold();
 Future<bool> canLeave() async=>doc?.dirty!=true || await confirmDiscard(context);
 Future<void> open(int id)async{
 if(busy||saving)return;
 if(!await canLeave()||!mounted||busy||saving)return;
 setState(()=>busy=true);
 try{
 final next=Document(await widget.api.open(id))..markClean();
 if(mounted)setState((){doc=next;selected=null;});
 }catch(e){if(mounted)notify(context,errorText(e));}
 finally{if(mounted)setState(()=>busy=false);}
 }
}
