       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTCOPY.
      * Same customer inquiry as CUSTINQ, but the layouts come from copybooks.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY CUSTFLD REPLACING ==:PFX:== BY ==WS==.
       01 WS-LAST-MESSAGE   PIC X(60).
       LINKAGE SECTION.
       01 DFHCOMMAREA.
       COPY CUSTCOMM.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF EIBCALEN = 0
               PERFORM FIRST-TIME-PARA
           ELSE
               PERFORM PROCESS-REQUEST
           END-IF.
           EXEC CICS RETURN TRANSID('CUST')
                COMMAREA(DFHCOMMAREA)
                LENGTH(LENGTH OF DFHCOMMAREA)
           END-EXEC.
       FIRST-TIME-PARA.
           MOVE SPACES TO CUST-MESSAGE.
           MOVE 'Enter customer id' TO CUST-MESSAGE.
           MOVE 0 TO CUST-RETURN-CODE.
       PROCESS-REQUEST.
           IF CUST-ID = SPACES
               MOVE 90 TO CUST-RETURN-CODE
               MOVE 'Customer id required' TO CUST-MESSAGE
           ELSE
               PERFORM READ-CUSTOMER
           END-IF.
       READ-CUSTOMER.
           EXEC CICS READ FILE('CUSTMAST')
                INTO(WS-REC)
                RIDFLD(CUST-ID)
                RESP(WS-RESP)
           END-EXEC.
           IF WS-RESP = 0
               MOVE WS-NAME TO CUST-NAME
               MOVE WS-BAL TO CUST-BALANCE
               MOVE 0 TO CUST-RETURN-CODE
           ELSE
               MOVE 91 TO CUST-RETURN-CODE
               MOVE 'Customer not found' TO CUST-MESSAGE
           END-IF.
           COPY CUSTMSG.
