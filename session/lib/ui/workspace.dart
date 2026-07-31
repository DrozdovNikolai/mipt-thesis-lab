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
}
