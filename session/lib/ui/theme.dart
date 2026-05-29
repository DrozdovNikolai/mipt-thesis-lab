import 'package:flutter/material.dart';
const panel=Color(0xff24262b);
const canvas=Color(0xff17191d);
const line=Color(0xff40434b);
const yellow=Color(0xffffd33d);
const muted=Color(0xffb2bac6);
ThemeData sessionTheme(){
 final colors=ColorScheme.fromSeed(seedColor:yellow,brightness:Brightness.dark).copyWith(primary:yellow,onPrimary:Colors.black,surface:panel);
 return ThemeData(useMaterial3:true,colorScheme:colors,scaffoldBackgroundColor:canvas,fontFamily:'Roboto',dividerColor:line,
 inputDecorationTheme:InputDecorationTheme(filled:true,fillColor:canvas,border:OutlineInputBorder(borderRadius:BorderRadius.circular(8))),
 filledButtonTheme:FilledButtonThemeData(style:FilledButton.styleFrom(minimumSize:const Size(48,44),shape:RoundedRectangleBorder(borderRadius:BorderRadius.circular(8)))));
}
