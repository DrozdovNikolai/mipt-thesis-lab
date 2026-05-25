String exerciseLabel(dynamic kind)=>switch(kind){
 'preparation'=>'Подготовка','coffee_break'=>'Перерыв','individual'=>'Индивидуальная работа','standard'=>'Упражнение',_=>kind?.toString()??'Упражнение'
};
String statusLabel(String status)=>switch(status.toUpperCase()){
 'DRAFT'=>'Черновик','PUBLISHED'=>'Опубликован','ARCHIVED'=>'В архиве',_=>status.isEmpty?'Без статуса':status
};
String durationLabel(int? value){
 if(value==null)return '—';
 if(value<60)return '$value мин';
 final rest=value%60;
 return '${value~/60} ч${rest==0?'':' $rest мин'}';
}
