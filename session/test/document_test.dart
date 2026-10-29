import 'package:flutter_test/flutter_test.dart';
import 'package:nord_session/model/document.dart';
import 'package:nord_session/model/catalog.dart';

Json example(int id,int position)=>{'id':id,'orderIndex':position,'kind':'standard','moduleId':7,'clientUid':'exercise-$id','elements':[{'id':18,'elementId':4,'orderIndex':0,'details':'ILS','startingHeight':1500,'profileType':'DOWN'}],'competences':[{'id':2,'code':'COM'}],'params':{'guidanceDoc':{'ops':[{'insert':'ILS'}]},'originalTl':{'id':3,'airportName':'UUWW'}}};
Document fixture()=>Document({'id':1,'contentVersion':9,'modules':[{'id':7,'scenarioId':1,'dayIndex':2,'orderIndex':0,'exercises':[example(12,10),example(14,30)]}]});

void main(){
 test('Reordering keeps rich guidance, element heights, crew competencies and day binding',(){
 final doc=fixture()..move(0,0,1);
 final module=doc.snapshot()['modules'].single;
 final first=module['exercises'].first;
 expect(module['dayIndex'],2);
 expect(first['id'],14);expect(first['orderIndex'],10);expect(first['competenceIds'],[2]);
 expect(first['elements'].single['startingHeight'],1500);
 expect(first['params']['guidanceDoc'],example(14,30)['params']['guidanceDoc']);
 expect(first['params']['originalTl'],{'airportName':'UUWW'});
 });
 test('Moving back or acknowledging the save clears pending changes',(){
 final doc=fixture(); expect(doc.dirty,isFalse);
 doc.move(0,1,0);expect(doc.dirty,isTrue);doc.move(0,0,1);expect(doc.dirty,isFalse);
 doc.move(0,0,1);doc.markClean();expect(doc.dirty,isFalse);
 });
}
