       IDENTIFICATION DIVISION.
       PROGRAM-ID. PARSEDEM.
      * Demo for local-variable tracking: 0500-PARSE-INPUT calls 0550-FIND-NEXT-DELIMITER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PARSE-AREA.
           05  WS-FUNC-LEN          PIC 9(03) VALUE 1.
           05  WS-FUNC-LEN-N-1      PIC 9(03).
           05  WS-START-POS         PIC 9(03).
           05  WS-CHAR-POS          PIC 9(03).
           05  WS-MOVE-LEN          PIC 9(03).
           05  WS-END-OF-DATA-SW    PIC X(01) VALUE 'N'.
           05  WS-TAB-CHAR          PIC X(01) VALUE X'09'.
       01  RCV-DATA-BUFFER-AREA     PIC X(200).
       01  ORRORL-LINE-REQUEST      PIC X(120).
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM 0500-PARSE-INPUT
           STOP RUN.
       0500-PARSE-INPUT.
           COMPUTE WS-FUNC-LEN-N-1 = WS-FUNC-LEN + 1
           MOVE WS-FUNC-LEN-N-1 TO WS-START-POS
           PERFORM 0550-FIND-NEXT-DELIMITER
           IF RCV-DATA-BUFFER-AREA(WS-CHAR-POS:1) = WS-TAB-CHAR
              MOVE RCV-DATA-BUFFER-AREA(WS-START-POS:WS-MOVE-LEN)
                   TO ORRORL-LINE-REQUEST
           ELSE
              MOVE SPACES TO ORRORL-LINE-REQUEST
           END-IF.
       0550-FIND-NEXT-DELIMITER.
           COMPUTE WS-CHAR-POS = WS-START-POS + 1
           IF WS-END-OF-DATA-SW = 'Y'
              MOVE 0 TO WS-MOVE-LEN
           ELSE
              COMPUTE WS-MOVE-LEN = WS-CHAR-POS - WS-START-POS
           END-IF.
