flowchart TB

  START(["매일 배치 시작"]) --> Q{"수집 데이터<br/>있는가?"}
  Q -->|"없음"| NA["'데이터 없음' 표시<br/>점수 산출 안 함"]
  Q -->|"있음"| C1

  C1["① 배당률 백분위 30점<br/>현재 배당률이<br/>자기 5년 밴드에서 상위 몇 %"]
  C1 --> C2["② 가격 위치 20점<br/>200일선 이격도<br/>+ 52주 밴드 위치"]
  C2 --> C3["③ 분배금 건강도 20점<br/>12개월 DPS vs 전년<br/>감액·중단 이력"]
  C3 --> C4["④ 총수익 정합성 10점<br/>분배율 vs 총수익률<br/>분배가 원금 깎는지"]
  C4 --> C5["⑤ 환율 백분위 10점<br/>USD/KRW 3년 위치<br/>원화투자자 관점"]
  C5 --> C6["⑥ 배당락 타이밍 10점<br/>ex-date 임박 감점<br/>직후 가점"]

  C6 --> SUM["합계 0~100<br/>+ 근거 문장 생성"]
  SUM --> CCQ{"커버드콜<br/>종목인가?"}
  CCQ -->|"예"| BADGE["'분배금 ≠ 수익' 배지<br/>점수와 무관하게 강제"]
  CCQ -->|"아니오"| GRADE
  BADGE --> GRADE

  GRADE{"점수 구간"}
  GRADE -->|"85 이상"| G1["적극매수<br/>+ 웹푸시 알람"]
  GRADE -->|"70~84"| G2["매수"]
  GRADE -->|"55~69"| G3["분할·관망"]
  GRADE -->|"55 미만"| G4["보류"]

  G1 --> SAVE[("score_snapshot 적재")]
  G2 --> SAVE
  G3 --> SAVE
  G4 --> SAVE

  classDef ok fill:#DDE6E4,stroke:#0E6F63,color:#0F1E3D
  classDef warn fill:#FBF0EA,stroke:#A63A18,color:#0F1E3D
  classDef core fill:#FFFFFF,stroke:#0F1E3D,color:#0F1E3D
  classDef store fill:#E9EDF2,stroke:#4A5872,color:#0F1E3D

  class G1 ok
  class NA,BADGE,G4 warn
  class C1,C2,C3,C4,C5,C6,SUM core
  class SAVE store
