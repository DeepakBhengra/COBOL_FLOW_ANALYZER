       IDENTIFICATION DIVISION.
       PROGRAM-ID. CNFGDEMO.
      * Demo for building a sample RCV-DATA-BUFFER-AREA from the tests in 0500-PARSE-INPUT and
      * 0570-MOVE-CONFIG-LINE. ORRCNFG is the configuration request copybook.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PARSE-AREA.
           05  WS-FUNCTION          PIC X(02).
           05  WS-NEXT-POS          PIC 9(03).
           05  WS-START-POS         PIC 9(03).
           05  WS-MOVE-LEN          PIC 9(03).
       01  RCV-DATA-BUFFER-AREA     PIC X(200).
       COPY ORRCNFG.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM 0500-PARSE-INPUT
           STOP RUN.
       0500-PARSE-INPUT.
           MOVE 1 TO WS-NEXT-POS
           MOVE RCV-DATA-BUFFER-AREA(WS-NEXT-POS:2) TO WS-FUNCTION
           EVALUATE WS-FUNCTION
              WHEN 'OL' OR 'CL' OR 'EC' OR 'ML' OR 'PT'
                 PERFORM 0570-MOVE-CONFIG-LINE
              WHEN OTHER
                 CONTINUE
           END-EVALUATE.
       0570-MOVE-CONFIG-LINE.
           MOVE LENGTH OF ORRCNFG-CNFG-REQUEST TO WS-MOVE-LEN
           MOVE 3 TO WS-START-POS
           IF RCV-DATA-BUFFER-AREA(WS-START-POS:2) = 'CF'
              MOVE RCV-DATA-BUFFER-AREA(WS-START-POS:WS-MOVE-LEN)
                   TO ORRCNFG-CNFG-REQUEST
           END-IF.
